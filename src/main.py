import os
import time
import docker
from src.docker_runner import RunnerManager
from src.config import load_runner_configs

class MaestroService:
    def __init__(self):
        self.docker_client = docker.from_env()
        # Load the runner configs for all repos/orgs
        self.runner_configs = load_runner_configs()
        self.runner_managers = []

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

    def launch_runners(self):
        for entry in self.runner_managers:
            mgr = entry["manager"]
            url = entry["url"]
            desired_count = entry["count"]
            labels = entry.get("labels", [])
            # Count already-running for this target
            running_containers = mgr.list_runner_containers()
            current_count = len(running_containers)
            print(f"[{url}] Currently running: {current_count} / Target: {desired_count}")
            needed = desired_count - current_count
            if needed <= 0:
                print(f"[{url}] No additional runners needed.")
                continue
            for i in range(current_count, desired_count):
                container = mgr.start_runner(index=i+1, labels=labels)
                print(f"[{url}] Launched runner container: {container.name}")

    def monitor_runners(self):
        for entry in self.runner_managers:
            mgr = entry["manager"]
            url = entry["url"]
            running = mgr.list_runner_containers()
            print(f"[{url}] Monitoring {len(running)} runner containers:")
            for c in running:
                print(f"  - {c.name}: {c.status}")
            # Future: crash/recovery logic per group

    def run(self):
        self.launch_runners()
        while True:
            self.monitor_runners()
            time.sleep(10)

if __name__ == "__main__":
    try:
        maestro = MaestroService()
        maestro.run()
    except Exception as e:
        print(f"MaestroService failed: {e}")