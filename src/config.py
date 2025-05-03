import os
import json

def load_runner_configs():
    """
    Load runner configuration from the RUNNERS_MATRIX JSON environment variable,
    or (for backward compatibility) use basic env vars for a single repo.
    Returns a list of runner specs: {url, count, labels, token, image}
    """
    runners_matrix = os.getenv("RUNNERS_MATRIX")
    if runners_matrix:
        runners = json.loads(runners_matrix)
        for entry in runners:
            entry["count"] = int(entry.get("count", 1))
            entry["labels"] = entry.get("labels", "").split(",") if isinstance(entry.get("labels", ""), str) else entry.get("labels", [])
            entry["token"] = entry.get("token") or os.getenv("GITHUB_PAT")
            entry["image"] = entry.get("image", os.getenv("RUNNER_IMAGE", "ercindedeoglu/gh-runner:latest"))
        return runners
    else:
        # Single runner setup (legacy env)
        return [{
            "url": os.getenv("RUNNER_URL"),
            "count": int(os.getenv("RUNNER_COUNT", 1)),
            "labels": os.getenv("RUNNER_LABELS", "").split(",") if os.getenv("RUNNER_LABELS") else [],
            "token": os.getenv("GITHUB_PAT"),
            "image": os.getenv("RUNNER_IMAGE", "ercindedeoglu/gh-runner:latest")
        }]