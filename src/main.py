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
                "ephemeral" if entry.get("ephemeral", True) else "persistent"
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
                    if container.get("status") == "running":
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
                running_processes = [
                    c
                    for c in mgr.list_runner_containers()
                    if c.get("status") == "running"
                ]
                current_count = len(running_processes)

                logger.info(
                    f"[{url}] Currently running: {current_count} / Target: {desired_count}"
                )

                needed = desired_count - current_count

                if needed < 0:
                    logger.info(
                        f"[{url}] Excess of {abs(needed)} runners scheduled, "
                        f"but not scaling down since isolated ephemeral runners will terminate automatically"
                    )
                    continue

                if needed == 0:
                    logger.debug(f"[{url}] Runner count matches target.")
                    continue

                # Launch missing runners
                launched = 0
                ephemeral = entry.get("ephemeral", True)
                disable_update = entry.get("disable_update", True)
                for i in range(current_count, desired_count):
                    if self._shutdown:
                        break

                    try:
                        process = mgr.start_runner(
                            index=i + 1,
                            labels=labels,
                            ephemeral=ephemeral,
                            disable_update=disable_update,
                        )
                        logger.info(
                            f"[{url}] Launched isolated runner process: {process.pid}"
                        )
                        launched += 1

                        # Small delay between launches to prevent overwhelming
                        time.sleep(2)

                    except Exception as e:
                        logger.error(f"[{url}] Failed to launch runner {i + 1}: {e}")

                if launched > 0:
                    logger.info(
                        f"[{url}] Successfully launched {launched} new isolated runners"
                    )

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
                processes = mgr.list_runner_containers()
                running = [c for c in processes if c.get("status") == "running"]
                completed = [c for c in processes if c.get("status") != "running"]

                logger.info(
                    f"[{url}] Status: {len(running)} running, {len(completed)} completed"
                )

                for process in processes:
                    logger.debug(
                        f"  - {process.get('name', 'unknown')}: {process.get('status')} (pid: {process.get('pid', 'N/A')})"
                    )

                # Completed processes are already cleaned up by subprocess tracking
                for process in completed:
                    logger.info(
                        f"[{url}] Process {process.get('name', 'unknown')} completed"
                    )

                if len(running) == 0:
                    logger.info(
                        f"[{url}] No runners running - system appears quiescent, ready for potential docker prune"
                    )
                    self._execute_docker_prune_if_safe()

            except Exception as e:
                logger.error(f"[{url}] Error during monitoring: {e}")

    def _execute_docker_prune_if_safe(self):
        import subprocess
        import time

        time.sleep(10)  # Wait to ensure all operations are complete

        total_running = 0
        for entry in self.runner_managers:
            mgr = entry["manager"]
            processes = mgr.list_runner_containers()
            running_processes = [c for c in processes if c.get("status") == "running"]
            total_running += len(running_processes)

        if total_running == 0:
            try:
                logger.info("System quiescent - executing docker system prune...")

                result_df_before = subprocess.run(
                    ["docker", "system", "df"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result_df_before.returncode == 0:
                    logger.info(
                        f"Docker system status before prune: {result_df_before.stdout}"
                    )

                result = subprocess.run(
                    ["docker", "system", "prune", "-a", "-f", "--volumes"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

                if result.returncode == 0:
                    logger.info(f"Docker prune successful: {result.stdout}")

                    result_df_after = subprocess.run(
                        ["docker", "system", "df"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                    if result_df_after.returncode == 0:
                        logger.info(
                            f"Docker system status after prune: {result_df_after.stdout}"
                        )
                else:
                    logger.error(f"Docker prune failed: {result.stderr}")

            except subprocess.TimeoutExpired:
                logger.error("Docker prune command timed out")
            except Exception as e:
                logger.error(f"Error executing docker prune: {e}")
        else:
            logger.info(
                f"Deferring docker prune - {total_running} processes now running"
            )

    def cleanup_runners(self):
        """Gracefully cleanup runner processes and containers"""
        logger.info("Initiating graceful shutdown of runner processes...")

        total_cleaned = 0

        for entry in self.runner_managers:
            mgr = entry["manager"]
            url = entry["url"]
            try:
                cleaned = mgr.cleanup_containers()
                total_cleaned += cleaned
                logger.info(f"[{url}] Cleaned up {cleaned} runner(s)")
            except Exception as e:
                logger.error(f"[{url}] Failed to cleanup runners: {e}")

        logger.info(f"Cleanup completed: {total_cleaned} runner(s) cleaned up")

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
