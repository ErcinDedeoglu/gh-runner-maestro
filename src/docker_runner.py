import docker
import os
import random
import string
import logging
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def random_suffix(length=8):
    """Generate a random suffix for container names"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

class RunnerManager:
    def __init__(self, docker_client, runner_image, runner_url, github_pat):
        self.docker_client = docker_client
        self.runner_image = runner_image
        self.runner_url = runner_url
        self.github_pat = github_pat
        
    def _sanitize_url_for_name(self, url: str) -> str:
        """Convert URL to a safe, short container name component"""
        parts = url.replace("https://", "").replace("http://", "").split("/")
        if len(parts) >= 2:
            # Use owner/repo for repos, or just the name for orgs
            return f"{parts[-2]}-{parts[-1]}" if len(parts) > 1 else parts[-1]
        return "default-runner"

    def start_runner(self, index: int, labels: Optional[List[str]] = None, extra_env: Optional[Dict[str, str]] = None) -> docker.models.containers.Container:
        """Start a single runner container with enhanced security and error handling"""
        try:
            # Pull the runner image
            logger.info(f"Pulling runner image: {self.runner_image}")
            self.docker_client.images.pull(self.runner_image)
            
            # Generate unique container name
            url_part = self._sanitize_url_for_name(self.runner_url)
            runner_name = f"runner-{url_part}-{index}-{random_suffix(6)}"
            
            # Prepare environment variables
            env = {
                "GITHUB_PAT": self.github_pat,
                "RUNNER_URL": self.runner_url,
                "RUNNER_NAME": runner_name
            }
            
            if labels:
                env["RUNNER_LABELS"] = ",".join(labels)
            if extra_env:
                env.update(extra_env)
            
            # Adaptive volume configuration - detect deployment mode
            volumes = {}
            deployment_mode = "unknown"
            
            # Check if Docker socket is available on the host
            if os.path.exists('/var/run/docker.sock'):
                # Docker socket mode - share the host Docker daemon
                volumes['/var/run/docker.sock'] = {'bind': '/var/run/docker.sock', 'mode': 'rw'}
                deployment_mode = "docker-socket"
                # Tell the runner image to skip starting its own Docker daemon
                env["DOCKER_HOST"] = "unix:///var/run/docker.sock"
                env["SKIP_DOCKER_DAEMON"] = "true"
                logger.info(f"Using Docker socket mode for container {runner_name}")
            else:
                # True DIND mode - mount cgroup for internal Docker daemon
                volumes['/sys/fs/cgroup'] = {'bind': '/sys/fs/cgroup', 'mode': 'rw'}
                deployment_mode = "docker-in-docker"
                logger.info(f"Using Docker-in-Docker mode for container {runner_name}")
            
            # Security-focused container configuration
            container_config = {
                "image": self.runner_image,
                "detach": True,
                "environment": env,
                "name": runner_name,
                "labels": {
                    "maestro.target_url": self.runner_url,
                    "maestro.managed": "true",
                    "maestro.created": str(int(time.time())),
                    "maestro.deployment_mode": deployment_mode
                },
                "auto_remove": False,
                "privileged": True,  # Required for Docker access
                "network_mode": "bridge",
                "volumes": volumes
            }
            
            logger.info(f"Launching runner container: {runner_name} for {self.runner_url}")
            logger.debug(f"Environment: {env}")
            
            container = self.docker_client.containers.run(**container_config)
            
            logger.info(f"Launched: {container.name} (id={container.short_id}, status={container.status})")
            return container
            
        except docker.errors.ImageNotFound as e:
            logger.error(f"Runner image not found: {self.runner_image}")
            raise
        except docker.errors.APIError as e:
            logger.error(f"Docker API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to start runner: {e}")
            raise

    def list_runner_containers(self) -> List[docker.models.containers.Container]:
        """Return containers managed by this manager with enhanced filtering"""
        try:
            containers = self.docker_client.containers.list(
                all=True,
                filters={
                    "ancestor": self.runner_image,
                    "label": f"maestro.target_url={self.runner_url}"
                }
            )
            
            # Filter to only include containers we manage
            managed_containers = [
                c for c in containers
                if c.labels.get("maestro.managed") == "true"
            ]
            
            logger.debug(f"Found {len(managed_containers)} managed containers for {self.runner_url}")
            return managed_containers
            
        except docker.errors.APIError as e:
            logger.error(f"Error listing containers: {e}")
            return []

    def get_container_stats(self) -> Dict[str, Any]:
        """Get statistics for containers managed by this manager"""
        containers = self.list_runner_containers()
        stats = {
            "total": len(containers),
            "running": 0,
            "exited": 0,
            "restarting": 0,
            "paused": 0,
            "containers": []
        }
        
        for container in containers:
            status = container.status
            stats[status] = stats.get(status, 0) + 1
            
            stats["containers"].append({
                "name": container.name,
                "id": container.short_id,
                "status": status,
                "created": container.attrs.get("Created", ""),
                "image": container.image.tags[0] if container.image.tags else container.image.id[:12]
            })
        
        return stats

    def cleanup_containers(self, force: bool = False) -> int:
        """Clean up containers for this manager"""
        containers = self.list_runner_containers()
        cleaned = 0
        
        for container in containers:
            try:
                if container.status == "running":
                    container.stop(timeout=30 if not force else 0)
                
                container.remove(force=force)
                logger.info(f"Cleaned up container: {container.name}")
                cleaned += 1
                
            except docker.errors.APIError as e:
                logger.error(f"Failed to cleanup container {container.name}: {e}")
                
        return cleaned