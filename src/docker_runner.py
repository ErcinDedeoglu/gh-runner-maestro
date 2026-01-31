from docker.errors import APIError
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
        # Track the subprocess PIDs of launched runners
        self.runner_processes = {}

    def _sanitize_url_for_name(self, url: str) -> str:
        """Convert URL to a safe, short container name component"""
        parts = url.replace("https://", "").replace("http://", "").split("/")
        if len(parts) >= 2:
            # Use owner/repo for repos, or just the name for orgs
            return f"{parts[-2]}-{parts[-1]}" if len(parts) > 1 else parts[-1]
        return "default-runner"

    def start_runner(
        self,
        index: int,
        labels: Optional[List[str]] = None,
        extra_env: Optional[Dict[str, str]] = None,
        ephemeral: bool = True,  # Changed default to True for isolation
        disable_update: bool = False,
    ):
        """Start a single runner container with --rm flag for complete isolation"""
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

            # Adaptive volume configuration - detect deployment mode
            volume_args = []
            deployment_mode = "unknown"

            # Check if Docker socket is available on the host
            if os.path.exists("/var/run/docker.sock"):
                # Docker socket mode - share the host Docker daemon
                volume_args.extend(
                    ["-v", "/var/run/docker.sock:/var/run/docker.sock:rw"]
                )
                deployment_mode = "docker-socket"
                # Tell the runner image to skip starting its own Docker daemon
                env_vars.extend(
                    [
                        "DOCKER_HOST=unix:///var/run/docker.sock",
                        "SKIP_DOCKER_DAEMON=true",
                    ]
                )
                logger.info(f"Using Docker socket mode for container {runner_name}")
            else:
                # True DIND mode - mount cgroup for internal Docker daemon
                volume_args.extend(["-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw"])
                deployment_mode = "docker-in-docker"
                logger.info(f"Using Docker-in-Docker mode for container {runner_name}")

            # Build the docker run command with --rm for complete isolation
            cmd = [
                "docker",
                "run",
                "--rm",  # This is critical for complete isolation - container is removed when it exits
                "--privileged",  # Required for Docker access
                "--network",
                "bridge",
            ]

            # Add environment variables
            for env_var in env_vars:
                cmd.extend(["-e", env_var])

            # Add volume mounts
            cmd.extend(volume_args)

            # Add image name
            cmd.append(self.runner_image)

            logger.info(
                f"Launching isolated runner container: {runner_name} for {self.runner_url}"
            )
            logger.debug(f"Docker command: {' '.join(cmd)}")

            # Start the container as a subprocess - completely isolated from maestro
            process = subprocess.Popen(cmd)

            # Store the subprocess reference
            self.runner_processes[runner_name] = {
                "process": process,
                "started_at": time.time(),
                "deployment_mode": deployment_mode,
            }

            logger.info(f"Launched isolated runner: {runner_name} (pid={process.pid})")
            return process

        except Exception as e:
            logger.error(f"Failed to start isolated runner: {e}")
            raise

    def list_runner_containers(self) -> List[Dict[str, Any]]:
        """Return information about isolated runner processes running via subprocess"""
        try:
            # Check which subprocess runner processes are still running
            running_processes = []
            for name, proc_info in list(self.runner_processes.items()):
                process = proc_info["process"]
                # Check if the process is still alive
                if process.poll() is None:  # Process is still running
                    running_processes.append(
                        {
                            "name": name,
                            "status": "running",
                            "pid": process.pid,
                            "started_at": proc_info["started_at"],
                            "deployment_mode": proc_info["deployment_mode"],
                        }
                    )
                else:
                    # Process has finished, remove it from tracking
                    del self.runner_processes[name]
                    logger.info(
                        f"Runner {name} has completed and been removed from tracking"
                    )

            # Also check for externally managed containers (if any) that may still exist
            try:
                containers = self.docker_client.containers.list(
                    all=True,
                    filters={
                        "ancestor": self.runner_image,
                        "label": f"maestro.target_url={self.runner_url}",
                    },
                )

                # Filter to only include containers we manage
                managed_containers = [
                    c for c in containers if c.labels.get("maestro.managed") == "true"
                ]

                # Add container info to the list
                for container in managed_containers:
                    running_processes.append(
                        {
                            "name": container.name,
                            "status": container.status,
                            "id": container.short_id,
                            "created": container.attrs.get("Created", ""),
                            "image": container.image.tags[0]
                            if container.image.tags
                            else container.image.id[:12],
                        }
                    )

            except APIError as e:
                logger.warning(
                    f"Error accessing Docker API for listing containers: {e}"
                )
                # Continue with just the subprocess tracking

            logger.debug(
                f"Found {len(running_processes)} active runner processes for {self.runner_url}"
            )
            return running_processes

        except Exception as e:
            logger.error(f"Error listing runner processes: {e}")
            return []

    def get_container_stats(self) -> Dict[str, Any]:
        """Get statistics for isolated runner processes"""
        processes = self.list_runner_containers()
        stats = {
            "total": len(processes),
            "running": 0,
            "completed": len(
                [
                    p
                    for p in self.runner_processes.values()
                    if p["process"].poll() is not None
                ]
            ),
            "processes": [],
        }

        for process in processes:
            if process.get("pid"):  # It's a subprocess
                stats["running"] += 1
                stats["processes"].append(
                    {
                        "name": process["name"],
                        "type": "subprocess",
                        "pid": process["pid"],
                        "status": process["status"],
                        "started_at": process["started_at"],
                        "deployment_mode": process.get("deployment_mode", "unknown"),
                    }
                )
            else:  # It's a traditional container
                stats[process["status"]] = stats.get(process["status"], 0) + 1
                stats["processes"].append(
                    {
                        "name": process["name"],
                        "type": "container",
                        "id": process.get("id", "unknown"),
                        "status": process["status"],
                        "created": process.get("created", ""),
                        "image": process.get("image", ""),
                    }
                )

        return stats

    def cleanup_containers(self, force: bool = False) -> int:
        """Clean up any remaining runner processes"""
        cleaned = 0

        # Terminate subprocess runners
        for name, proc_info in list(self.runner_processes.items()):
            process = proc_info["process"]
            try:
                if process.poll() is None:  # Process is still running
                    logger.info(
                        f"Terminating runner process: {name} (pid={process.pid})"
                    )
                    process.terminate()
                    try:
                        process.wait(
                            timeout=30
                        )  # Wait up to 30 seconds for graceful termination
                    except subprocess.TimeoutExpired:
                        logger.warning(
                            f"Process {name} didn't terminate gracefully, killing it"
                        )
                        process.kill()
                        process.wait()
                    cleaned += 1
            except Exception as e:
                logger.error(f"Failed to terminate process {name}: {e}")

        # Clear the tracking dict
        self.runner_processes.clear()

        # Also try to clean up any traditional containers that might exist
        try:
            containers = self.docker_client.containers.list(
                all=True,
                filters={
                    "ancestor": self.runner_image,
                    "label": f"maestro.target_url={self.runner_url}",
                },
            )

            managed_containers = [
                c for c in containers if c.labels.get("maestro.managed") == "true"
            ]

            for container in managed_containers:
                try:
                    if container.status == "running":
                        container.stop(timeout=30 if not force else 0)
                    container.remove(force=force)
                    logger.info(f"Cleaned up container: {container.name}")
                    cleaned += 1
                except APIError as e:
                    logger.error(f"Failed to cleanup container {container.name}: {e}")

        except APIError as e:
            logger.warning(f"Error accessing Docker API for cleanup: {e}")

        return cleaned
