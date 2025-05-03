import docker
import os
import random
import string

def random_suffix(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

class RunnerManager:
    def __init__(self, docker_client, runner_image, runner_url, github_pat):
        self.docker_client = docker_client
        self.runner_image = runner_image
        self.runner_url = runner_url
        self.github_pat = github_pat

    def start_runner(self, index, labels=None, extra_env=None):
        """Start a single runner container"""
        runner_name = f"gh-runner-{index}-{random_suffix(4)}"
        env = {
            "GITHUB_PAT": self.github_pat,
            "RUNNER_URL": self.runner_url,
            "RUNNER_NAME": runner_name
        }
        if labels:
            env["RUNNER_LABELS"] = ",".join(labels)
        if extra_env:
            env.update(extra_env)

        print(f"Launching runner container: {runner_name}")

        container = self.docker_client.containers.run(
            self.runner_image,
            detach=True,
            environment=env,
            name=runner_name,
            auto_remove=True,
            privileged=True,
            network_mode="bridge"
        )
        return container

    def list_runner_containers(self):
        """Return containers started by this manager."""
        containers = self.docker_client.containers.list(
            all=True,
            filters={"ancestor": self.runner_image, "status": "running"}
        )
        res = []
        for c in containers:
            if c.name.startswith("gh-runner-"):
                res.append(c)
        return res