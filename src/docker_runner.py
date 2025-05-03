import docker
import os
import random
import string

def random_suffix(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

class RunnerManager:
    def __init__(self, docker_client, runner_image, runner_url, github_pat):
        self.docker_client = docker_client
        self.runner_image = runner_image
        self.runner_url = runner_url
        self.github_pat = github_pat

    def start_runner(self, index, labels=None, extra_env=None):
        """Start a single runner container fully DinD-isolated. Makes name globally unique."""
        # Always pull the runner image before starting to ensure the latest version is used
        self.docker_client.images.pull(self.runner_image)

        runner_name = f"gh-runner-{index}-{random_suffix(8)}"
        env = {
            "GITHUB_PAT": self.github_pat,
            "RUNNER_URL": self.runner_url,
            "RUNNER_NAME": runner_name
        }
        if labels:
            env["RUNNER_LABELS"] = ",".join(labels)
        if extra_env:
            env.update(extra_env)

        print(f"[Orchestrator] Launching runner container: {runner_name} for {self.runner_url}")
        print(f"  Env: {env}")

        container = self.docker_client.containers.run(
            self.runner_image,
            detach=True,
            environment=env,
            name=runner_name,
            labels={"maestro.target_url": self.runner_url},
            auto_remove=False,  # For debugging, let us inspect stopped containers
            privileged=True,
            network_mode="bridge"
        )
        print(f"[Orchestrator] Launched: {container.name} id={container.short_id} status={container.status}")
        return container

    def list_runner_containers(self):
        """Return containers started by this manager."""
        containers = self.docker_client.containers.list(
            all=True,
            filters={
                "ancestor": self.runner_image,
                "label": f"maestro.target_url={self.runner_url}"
            }
        )
        print(f"[Orchestrator] All containers for {self.runner_url}:")
        for c in containers:
            print(f"   {c.name}: status={c.status}, id={c.short_id}, exit={getattr(c, 'exitcode', None)}")
        res = []
        for c in containers:
            if c.name.startswith("gh-runner-"):
                res.append(c)
        return res