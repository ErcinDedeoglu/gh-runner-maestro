import os
import random
import string
import logging
import time
import subprocess
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def random_suffix(length=8):
    """Generate a random suffix for container names"""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


class RunnerManager:
    def __init__(self, docker_client, runner_image, runner_url, github_pat):
        self.docker_client = docker_client
        self.runner_image = runner_image
        self.runner_url = runner_url
        self.github_pat = github_pat
        self.runner_processes = {}

    def _sanitize_url_for_name(self, url: str) -> str:
        """Convert URL to a safe, short container name component"""
        parts = url.replace("https://", "").replace("http://", "").split("/")
        if len(parts) >= 2:
            # Use owner/repo for repos, or just the name for orgs
            return f"{parts[-2]}-{parts[-1]}" if len(parts) > 1 else parts[-1]
        return "default-runner"

    def _detect_docker_mode(self) -> str:
        """
        Determine Docker mode for runner containers.

        Default is 'standalone' - each runner gets its own isolated Docker daemon.
        Can be overridden with DOCKER_MODE env var if shared Docker is needed.
        """
        explicit_mode = os.getenv("DOCKER_MODE", "").lower()
        if explicit_mode in ("host-socket", "dind", "standalone"):
            return explicit_mode

        # Default to standalone - runners are fully isolated with their own Docker daemon
        return "standalone"

    def start_runner(
        self,
        index: int,
        labels: Optional[List[str]] = None,
        extra_env: Optional[Dict[str, str]] = None,
        ephemeral: bool = True,  # Changed default to True for isolation
        disable_update: bool = False,
    ):
        """Start a single runner container with proper labeling for lifecycle management"""
        try:
            # Generate unique container name
            url_part = self._sanitize_url_for_name(self.runner_url)
            runner_name = f"runner-{url_part}-{index}-{random_suffix(6)}"

            # Prepare environment variables
            env_vars = [
                f"GITHUB_PAT={self.github_pat}",
                f"RUNNER_URL={self.runner_url}",
                f"RUNNER_NAME={runner_name}",
            ]

            if labels:
                env_vars.append(f"RUNNER_LABELS={','.join(labels)}")
            if ephemeral:
                env_vars.append("RUNNER_EPHEMERAL=true")
            if disable_update:
                env_vars.append("RUNNER_DISABLE_UPDATE=true")
            if extra_env:
                for key, value in extra_env.items():
                    env_vars.append(f"{key}={value}")

            volume_args = []
            deployment_mode = self._detect_docker_mode()

            if deployment_mode in ("host-socket", "dind"):
                volume_args.extend(
                    ["-v", "/var/run/docker.sock:/var/run/docker.sock:rw"]
                )
                env_vars.extend(
                    [
                        "DOCKER_HOST=unix:///var/run/docker.sock",
                        "SKIP_DOCKER_DAEMON=true",
                    ]
                )
            else:
                volume_args.extend(["-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw"])

            logger.info(f"Using {deployment_mode} mode for container {runner_name}")

            cmd = [
                "docker",
                "run",
                "-d",
                "--rm",
                "--privileged",
                "--name",
                runner_name,
                "--network",
                "bridge",
                "--label",
                "maestro.managed=true",
                "--label",
                f"maestro.target_url={self.runner_url}",
                "--label",
                f"maestro.runner_image={self.runner_image}",
                "--label",
                f"maestro.started_at={time.time()}",
            ]

            # Add environment variables
            for env_var in env_vars:
                cmd.extend(["-e", env_var])

            # Add volume mounts
            cmd.extend(volume_args)

            # Add image name
            cmd.append(self.runner_image)

            logger.info(
                f"Launching runner container: {runner_name} for {self.runner_url}"
            )
            logger.debug(f"Docker command: {' '.join(cmd)}")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                logger.error(
                    f"Failed to start container {runner_name}: {result.stderr}"
                )
                raise RuntimeError(f"Docker run failed: {result.stderr}")

            container_id = result.stdout.strip()[:12]

            self.runner_processes[runner_name] = {
                "container_id": container_id,
                "started_at": time.time(),
                "deployment_mode": deployment_mode,
            }

            logger.info(f"Launched runner: {runner_name} (container_id={container_id})")
            return runner_name

        except Exception as e:
            logger.error(f"Failed to start runner: {e}")
            raise

    def list_runner_containers(self) -> List[Dict[str, Any]]:
        """List all runner containers managed by maestro for this URL"""
        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    "label=maestro.managed=true",
                    "--filter",
                    f"label=maestro.target_url={self.runner_url}",
                    "--format",
                    "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.CreatedAt}}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.warning(f"Failed to list containers: {result.stderr}")
                return []

            containers = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    status = parts[2].lower()
                    containers.append(
                        {
                            "id": parts[0],
                            "name": parts[1],
                            "status": "running"
                            if status.startswith("up")
                            else "exited",
                            "created": parts[3] if len(parts) > 3 else "",
                        }
                    )

            logger.debug(
                f"Found {len(containers)} runner containers for {self.runner_url}"
            )
            return containers

        except subprocess.TimeoutExpired:
            logger.error("Timeout listing runner containers")
            return []
        except Exception as e:
            logger.error(f"Error listing runner containers: {e}")
            return []

    def get_container_stats(self) -> Dict[str, Any]:
        """Get statistics for runner containers"""
        containers = self.list_runner_containers()
        running = [c for c in containers if c.get("status") == "running"]
        exited = [c for c in containers if c.get("status") == "exited"]

        return {
            "total": len(containers),
            "running": len(running),
            "exited": len(exited),
            "containers": containers,
        }

    def cleanup_containers(self, force: bool = False) -> int:
        """Stop and remove all runner containers for this URL"""
        cleaned = 0

        try:
            containers = self.list_runner_containers()

            for container in containers:
                container_name = container.get("name")
                if not container_name:
                    continue

                try:
                    logger.info(f"Stopping runner container: {container_name}")

                    timeout = "0" if force else "30"
                    stop_result = subprocess.run(
                        ["docker", "stop", "-t", timeout, container_name],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )

                    if stop_result.returncode == 0:
                        logger.info(f"Stopped container: {container_name}")
                        cleaned += 1
                    else:
                        logger.warning(
                            f"Failed to stop {container_name}: {stop_result.stderr}"
                        )
                        if force:
                            kill_result = subprocess.run(
                                ["docker", "kill", container_name],
                                capture_output=True,
                                text=True,
                                timeout=30,
                            )
                            if kill_result.returncode == 0:
                                logger.info(f"Force killed container: {container_name}")
                                cleaned += 1

                except subprocess.TimeoutExpired:
                    logger.error(f"Timeout stopping container {container_name}")
                except Exception as e:
                    logger.error(f"Failed to cleanup container {container_name}: {e}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        self.runner_processes.clear()
        return cleaned
