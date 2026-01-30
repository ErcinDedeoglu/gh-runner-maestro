import os
import time
import docker
import signal
import sys
import logging
import json
from datetime import datetime, timezone
from docker_runner import RunnerManager
from config import load_runner_configs

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/var/log/gh-runner-maestro/maestro.log")
        if os.path.exists("/var/log/gh-runner-maestro")
        else logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class MaestroService:
    def __init__(self):
        self.docker_client = docker.from_env()
        self.runner_configs = load_runner_configs()
        self.runner_managers = []
        self._shutdown = False

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

        # Validate configurations
        self._validate_configs()

        # Initialize managers
        self._initialize_managers()

        logger.info("Maestro service initialized successfully")

    def _validate_configs(self):
        """Validate runner configurations"""
        for entry in self.runner_configs:
            if not entry.get("url"):
                raise ValueError("Each runner config must specify a URL")
            if not entry.get("token"):
                logger.warning(
                    f"No token provided for {entry['url']}, using DEFAULT_RUNNER_TOKEN"
                )
                entry["token"] = os.getenv("DEFAULT_RUNNER_TOKEN")
                if not entry["token"]:
                    raise ValueError(f"No token available for {entry['url']}")

    def _initialize_managers(self):
        """Initialize runner managers"""
        for entry in self.runner_configs:
            mgr = RunnerManager(
                self.docker_client, entry["image"], entry["url"], entry["token"]
            )
            entry["manager"] = mgr
            self.runner_managers.append(entry)
            ephemeral_mode = (
                "ephemeral" if entry.get("ephemeral", False) else "persistent"
            )
            logger.info(
                f"Configured: {entry['count']} runners for {entry['url']} [labels={entry['labels']}, mode={ephemeral_mode}]"
            )

    def handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self._shutdown = True

    def health_check(self):
        """Perform health checks on the service"""
        try:
            # Check Docker daemon connectivity
            self.docker_client.ping()

            # Check runner containers
            total_containers = 0
            healthy_containers = 0

            for entry in self.runner_managers:
                mgr = entry["manager"]
                containers = mgr.list_runner_containers()
                total_containers += len(containers)

                for container in containers:
                    if container.status == "running":
                        healthy_containers += 1

            return {
                "status": "healthy",
                "docker_connected": True,
                "total_containers": total_containers,
                "healthy_containers": healthy_containers,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def launch_runners(self):
        """Launch runner containers with proper error handling"""
        for entry in self.runner_managers:
            if self._shutdown:
                break

            mgr = entry["manager"]
            url = entry["url"]
            desired_count = entry["count"]
            labels = entry.get("labels", [])

            try:
                running_containers = [
                    c for c in mgr.list_runner_containers() if c.status == "running"
                ]
                current_count = len(running_containers)

                logger.info(
                    f"[{url}] Currently running: {current_count} / Target: {desired_count}"
                )

                needed = desired_count - current_count
                if needed <= 0:
                    logger.info(f"[{url}] No additional runners needed.")
                    continue

                # Launch missing runners
                launched = 0
                ephemeral = entry.get("ephemeral", False)
                disable_update = entry.get("disable_update", True)
                for i in range(current_count, desired_count):
                    if self._shutdown:
                        break

                    try:
                        container = mgr.start_runner(
                            index=i + 1,
                            labels=labels,
                            ephemeral=ephemeral,
                            disable_update=disable_update,
                        )
                        logger.info(
                            f"[{url}] Launched runner container: {container.name}"
                        )
                        launched += 1

                        # Small delay between launches to prevent overwhelming
                        time.sleep(2)

                    except Exception as e:
                        logger.error(f"[{url}] Failed to launch runner {i + 1}: {e}")

                if launched > 0:
                    logger.info(f"[{url}] Successfully launched {launched} new runners")

            except Exception as e:
                logger.error(f"[{url}] Error during runner launch: {e}")

    def monitor_runners(self):
        """Monitor runner containers and handle failures"""
        for entry in self.runner_managers:
            if self._shutdown:
                break

            mgr = entry["manager"]
            url = entry["url"]

            try:
                containers = mgr.list_runner_containers()
                running = [c for c in containers if c.status == "running"]
                exited = [c for c in containers if c.status == "exited"]

                logger.info(
                    f"[{url}] Status: {len(running)} running, {len(exited)} exited"
                )

                # Log container details
                for container in containers:
                    logger.debug(f"  - {container.name}: {container.status}")

                # Handle crashed containers
                for container in exited:
                    try:
                        exit_code = container.attrs.get("State", {}).get(
                            "ExitCode", "unknown"
                        )
                        logger.warning(
                            f"[{url}] Container {container.name} exited with code {exit_code}"
                        )

                        # Remove crashed containers
                        container.remove(force=True)
                        logger.info(
                            f"[{url}] Removed crashed container: {container.name}"
                        )

                    except Exception as e:
                        logger.error(f"[{url}] Error handling crashed container: {e}")

            except Exception as e:
                logger.error(f"[{url}] Error during monitoring: {e}")

    def cleanup_runners(self):
        """Gracefully cleanup runner containers"""
        logger.info("Initiating graceful shutdown of runner containers...")

        cleanup_success = 0
        cleanup_failed = 0

        for entry in self.runner_managers:
            mgr = entry["manager"]
            containers = mgr.list_runner_containers()

            for container in containers:
                try:
                    logger.info(f"Stopping container: {container.name}")
                    container.stop(timeout=30)
                    container.remove(force=True)
                    cleanup_success += 1
                    logger.info(f"Successfully cleaned up: {container.name}")

                except Exception as e:
                    logger.error(f"Failed to cleanup {container.name}: {e}")
                    cleanup_failed += 1

        logger.info(
            f"Cleanup completed: {cleanup_success} successful, {cleanup_failed} failed"
        )

    def run(self):
        """Main service loop"""
        logger.info("Starting Maestro service...")

        try:
            # Initial health check
            health = self.health_check()
            if health["status"] != "healthy":
                logger.error("Initial health check failed, exiting...")
                return

            # Launch initial runners
            self.launch_runners()

            # Main monitoring loop
            while not self._shutdown:
                try:
                    self.monitor_runners()

                    # Relaunch missing runners
                    self.launch_runners()

                    # Health check every 5 minutes
                    if int(time.time()) % 300 == 0:
                        health = self.health_check()
                        logger.info(f"Health check: {json.dumps(health)}")

                    time.sleep(30)  # Monitor every 30 seconds

                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    time.sleep(10)

        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        except Exception as e:
            logger.error(f"Fatal error in MaestroService: {e}", exc_info=True)
        finally:
            self.cleanup_runners()
            logger.info("Maestro service stopped")


if __name__ == "__main__":
    try:
        maestro = MaestroService()
        maestro.run()
    except Exception as e:
        logger.error(f"Failed to start MaestroService: {e}", exc_info=True)
        sys.exit(1)
