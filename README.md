# gh-runner-maestro

**Maestro** orchestrates multiple self-hosted GitHub Actions runner containers—across one or more repositories/organizations—using Docker, all manageable via a single container and Docker Compose.

## Features

- Dynamically manage runner containers for one or multiple repositories/orgs
- Isolated sibling containers; full control of count, labeling, and image per runner group
- Single orchestrator (maestro) container configuration—no per-repo duplication required
- Health monitoring and auto-recovery for crashed/stuck runners

## Prerequisites

- Docker must be available on the host
- Requires the Docker socket to be mounted (`-v /var/run/docker.sock:/var/run/docker.sock`)
- GitHub Personal Access Tokens for each repo or org as needed

## Docker-in-Docker Support

This container supports both Docker socket mounting and true Docker-in-Docker (DIND) modes:

### Docker Socket Mode (Recommended)
Mount the host Docker socket for better performance:
```bash
docker run -d --name gh-runner-maestro \
  --privileged \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e RUNNERS_MATRIX='[...]' \
  gh-runner-maestro:latest
```

### True Docker-in-Docker Mode
Run without mounting the Docker socket for complete isolation:
```bash
docker run -d --name gh-runner-maestro \
  --privileged \
  -e RUNNERS_MATRIX='[...]' \
  gh-runner-maestro:latest
```

**Features:**
- ✅ Automatic cgroup v1 configuration for compatibility
- ✅ Clean logs without cgroup errors
- ✅ Proper resource management in both modes
- ✅ No additional configuration required

---

## Multi-Repository/Org Support & Configuration

Define runner groups using the `RUNNERS_MATRIX` environment variable in your `docker-compose.yml`. We recommend using a multi-line YAML block for readability, with in-line documentation:

```yaml
services:
  gh-runner-maestro:
    image: gh-runner-maestro:latest
    privileged: true
    environment:
      # Optional: Set a global default token for all runners lacking an explicit "token"
      # - DEFAULT_RUNNER_TOKEN=YOUR_COMMON_GITHUB_TOKEN

      # RUNNERS_MATRIX parameters:
      #   url:            GitHub repository or organization URL, e.g. "https://github.com/your-org/your-repo1" or "https://github.com/your-org"
      #   count:          Number of runners (containers) to launch for this url
      #   labels:         Comma-separated labels for the runner(s)
      #   token:          GitHub Personal Access Token (PAT) with registration permissions
      #   image:          (optional) Docker image for the runner (with tag); omitted means default "dublok/gh-runner:latest"
      #   ephemeral:      (optional, default: true) If true, runners terminate after one job and auto-cleanup
      #   disable_update: (optional, default: true) If true, skip automatic image pulls for faster launches
      - RUNNERS_MATRIX: |
          [
            {"url":"https://github.com/your-org/your-repo1",  "count":3, "labels":"dind,ubuntu-latest", "token":"YOUR_GITHUB_TOKEN_1", "image":"dublok/gh-runner:v1"},
            {"url":"https://github.com/your-org/your-repo2",  "count":3, "labels":"dind,ubuntu-latest", "token":"YOUR_GITHUB_TOKEN_2", "image":"dublok/gh-runner:v1.0.11"},
            {"url":"https://github.com/your-org",             "count":2, "labels":"org-scope",          "token":"YOUR_ORG_LEVEL_GITHUB_TOKEN"}
          ]
    # volumes:
    #   - /var/run/docker.sock:/var/run/docker.sock   # For Docker-in-Docker. Remove for full isolation.
    restart: unless-stopped
```

> **Note:** If you want to use environment variable interpolation (recommended for secrets), use `${VAR}` in the JSON or define the matrix in your `.env` file.
> 
> **Per-runner `token` takes precedence over `DEFAULT_RUNNER_TOKEN`.** If neither are set, the legacy fallback is `GITHUB_PAT`.
>
> **NEVER commit real tokens to source control.** Use `.env` files (ignored by git) or CI/CD secrets for sensitive data.

---

## RUNNERS_MATRIX Parameter Reference

| Parameter       | Type    | Required | Default | Example                                   | Description                                                                                 |
|-----------------|---------|----------|---------|-------------------------------------------|---------------------------------------------------------------------------------------------|
| url             | string  | Yes      | -       | "https://github.com/your-org/your-repo1"  | GitHub repository *or* organization URL to register the runner(s) with                      |
| count           | int     | Yes      | -       | 3                                         | Number of runner containers for this target (>=1)                                           |
| labels          | string  | Yes      | -       | "dind,ubuntu-latest"                      | Comma-separated labels for the runner(s), visible in Actions matrix/targeted jobs           |
| token           | string  | Yes*     | -       | "YOUR_GITHUB_TOKEN"                       | GitHub PAT with registration permission; fallback to DEFAULT_RUNNER_TOKEN or GITHUB_PAT     |
| image           | string  | No       | `dublok/gh-runner:latest` | "dublok/gh-runner:v1.0.11" | Docker image for runner (with tag/digest)                                    |
| ephemeral       | bool    | No       | `true`  | true                                      | If true, runners auto-terminate after one job. Recommended for isolation and auto-cleanup   |
| disable_update  | bool    | No       | `true`  | true                                      | If true, skips automatic image pulls before container start for faster launches             |

\* `token` is optional if `DEFAULT_RUNNER_TOKEN` is provided (globally), otherwise required per-runner entry.

### Example: Organization-level Runners

To register runners at the organization level, simply set `url` to your organization (e.g., `"https://github.com/your-org"`) in an entry as shown above.

### Example: Image Tag Versions

You can specify a particular runner image for any entry (`image`). If omitted, your runner will use `dublok/gh-runner:latest` by default.

---

## Runner Isolation & Docker Resource Management

Maestro uses an **isolated runner architecture** for improved reliability and resource management:

### Ephemeral Runner Mode (Default)

By default, runners operate in **ephemeral mode** (`ephemeral: true`):

- ✅ Each runner container automatically terminates after completing one job
- ✅ Containers are launched with Docker's `--rm` flag for automatic cleanup
- ✅ No manual container cleanup required
- ✅ Prevents resource accumulation and stale containers

### Automatic Docker Pruning

When all runners are idle (no jobs running), Maestro automatically:

1. **Detects system quiescence** - waits 10 seconds to ensure stability
2. **Executes `docker system prune`** - removes:
   - Stopped containers
   - Dangling images
   - Unused volumes
   - Build cache
3. **Logs resource cleanup** - shows before/after disk usage

This ensures Docker resources don't accumulate over time, especially important for:
- Long-running deployments
- High-volume CI/CD environments
- Resource-constrained hosts

### Persistent Runner Mode

For special use cases, you can disable ephemeral mode:

```json
{"url": "...", "count": 2, "labels": "...", "token": "...", "ephemeral": false}
```

**Note:** Persistent runners don't auto-terminate and won't trigger automatic docker prune.

---

## Usage (Single Repo/Org, Legacy)

Alternatively, the original method is still supported with direct environment variables:

- `GITHUB_PAT`, `RUNNER_URL`, `RUNNER_COUNT`, `RUNNER_LABELS`, `RUNNER_IMAGE`

---

## How It Works

On startup, maestro reads the `RUNNERS_MATRIX` JSON env var (via docker-compose), and dynamically manages all requested runners. If the matrix is not specified, it looks for the legacy direct environment variable set for a single runner.

### Automatic Image Updates

**Important:** The system automatically pulls the latest version of the runner image before starting each container. This ensures that:

- ✅ Security updates are automatically applied
- ✅ Latest features and bug fixes are used
- ✅ No manual image management required

When a runner container is started, the system executes `docker pull <runner-image>` to fetch the most recent version. This applies to both the default `dublok/gh-runner:latest` image and any custom images specified in the `RUNNERS_MATRIX` configuration.

---

## Building the Maestro Container

The Dockerfile is located in the `src/` folder. Build from the repo root:

```bash
docker build -t gh-runner-maestro:latest src
```

---

## Project Structure

- `src/`: Python source for the orchestration service and Dockerfile
- `requirements.txt`: Python dependencies
- `docker-compose.yml`: Compose file to launch the maestro service

---

## License

MIT