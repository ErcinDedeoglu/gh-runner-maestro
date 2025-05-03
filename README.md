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
      #   url:    GitHub repository or organization URL, e.g. "https://github.com/your-org/your-repo1" or "https://github.com/your-org"
      #   count:  Number of runners (containers) to launch for this url
      #   labels: Comma-separated labels for the runner(s)
      #   token:  GitHub Personal Access Token (PAT) with registration permissions
      #   image:  (optional) Docker image for the runner (with tag); omitted means default "dublok/gh-runner:latest"
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

| Parameter | Type    | Required | Example                                   | Description                                                                                 |
|-----------|---------|----------|-------------------------------------------|---------------------------------------------------------------------------------------------|
| url       | string  | Yes      | "https://github.com/your-org/your-repo1"  | GitHub repository *or* organization URL to register the runner(s) with                      |
| count     | int     | Yes      | 3                                         | Number of runner containers for this target (>=1)                                           |
| labels    | string  | Yes      | "dind,ubuntu-latest"                      | Comma-separated labels for the runner(s), visible in Actions matrix/targeted jobs           |
| token     | string  | Yes*     | "YOUR_GITHUB_TOKEN"                       | GitHub PAT with registration permission; fallback to DEFAULT_RUNNER_TOKEN or GITHUB_PAT     |
| image     | string  | No       | "dublok/gh-runner:v1.0.11"                | Docker image for runner (with tag/digest); omitted means defaults to dublok/gh-runner:latest|

\* `token` is optional if `DEFAULT_RUNNER_TOKEN` is provided (globally), otherwise required per-runner entry.

### Example: Organization-level Runners

To register runners at the organization level, simply set `url` to your organization (e.g., `"https://github.com/your-org"`) in an entry as shown above.

### Example: Image Tag Versions

You can specify a particular runner image for any entry (`image`). If omitted, your runner will use `dublok/gh-runner:latest` by default.

---

## Usage (Single Repo/Org, Legacy)

Alternatively, the original method is still supported with direct environment variables:

- `GITHUB_PAT`, `RUNNER_URL`, `RUNNER_COUNT`, `RUNNER_LABELS`, `RUNNER_IMAGE`

---

## How It Works

On startup, maestro reads the `RUNNERS_MATRIX` JSON env var (via docker-compose), and dynamically manages all requested runners. If the matrix is not specified, it looks for the legacy direct environment variable set for a single runner.

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