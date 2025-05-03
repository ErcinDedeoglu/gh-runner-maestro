import os
import time
import docker
import signal
import sys
from docker_runner import RunnerManager
from config import load_runner_configs

class MaestroService:
    def __init__(self):
        self.docker_client = docker.from_env()
        # Load the runner configs for all repos/orgs
        self.runner_configs = load_runner_configs()
        self.runner_managers = []

        # Buffer time between launches for same repo (default 5 seconds, config via env)
        self.runner_launch_buffer = float(os.getenv("RUNNER_LAUNCH_BUFFER", "5"))

        for entry in self.runner_configs:
            if not entry["url"] or not entry["token"]:
                raise ValueError("Each runner config must specify url and token.")
            mgr = RunnerManager(
                self.docker_client,
                entry["image"],
                entry["url"],
                entry["token"]
            )
            entry["manager"] = mgr
            self.runner_managers.append(entry)
            print(f"Configured: {entry['count']} runners for {entry['url']} [labels={entry['labels']}]")

        self._shutdown = False
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

    def handle_signal(self, signum, frame):
        print("Received shutdown signal, force-killing runner containers...")
        self._shutdown = True

    def launch_runners(self):
        for entry in self.runner_managers:
            mgr = entry["manager"]
            url = entry["url"]
            desired_count = entry["count"]
            labels = entry.get("labels", [])
            running_containers = [c for c in mgr.list_runner_containers() if c.status == "running"]
            current_count = len(running_containers)
            print(f"[{url}] Currently running: {current_count} / Target: {desired_count}")
            needed = desired_count - current_count
            if needed <= 0:
                print(f"[{url}] No additional runners needed.")
                continue
            for i in range(current_count, desired_count):
                container = mgr.start_runner(index=i+1, labels=labels)
                print(f"[{url}] Launched runner container: {container.name}")
                # Add buffer between launches for the same repo/org
                if i < desired_count - 1:
                    print(f"[{url}] Waiting {self.runner_launch_buffer} seconds before next runner launch...")
                    time.sleep(self.runner_launch_buffer)

    def monitor_runners(self):
        for entry in self.runner_managers:
            mgr = entry["manager"]
            url = entry["url"]
            running = [c for c in mgr.list_runner_containers() if c.status == "running"]
            print(f"[{url}] Monitoring {len(running)} runner containers:")
            for c in running:
                print(f"  - {c.name}: {c.status}")
            # Future: crash/recovery logic per group

    def cleanup_runners(self):
        print("Force killing and removing all managed runner containers...")
        for entry in self.runner_managers:
            mgr = entry["manager"]
            containers = mgr.list_runner_containers()
            for c in containers:
                try:
                    print(f"Killing {c.name}")
                    c.kill()
                except Exception as e:
                    print(f"Error killing {c.name}: {e}")
                try:
                    print(f"Removing {c.name}")
                    c.remove(force=True)
                except Exception as e:
                    print(f"Error removing {c.name}: {e}")
        print("All managed runner containers killed and removed.")

    def run(self):
        self.launch_runners()
        try:
            while not self._shutdown:
                self.monitor_runners()
                time.sleep(10)
        finally:
            self.cleanup_runners()

if __name__ == "__main__":
    try:
        maestro = MaestroService()
        maestro.run()
    except Exception as e:
        print(f"MaestroService failed: {e}")