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

## Multi-Repository/Org Support (via environment JSON)

To define multiple runner groups, set the `RUNNERS_MATRIX` environment variable in docker-compose.yml as a JSON string. Example snippet:

```yaml
services:
  gh-runner-maestro:
    image: gh-runner-maestro:latest
    privileged: true
    environment:
      - RUNNERS_MATRIX=[
          {"url":"https://github.com/org1/repo1","count":2,"labels":"dind,ubuntu-latest","token":"${GITHUB_PAT_REPO1}"},
          {"url":"https://github.com/org2/repo2","count":1,"labels":"docker","token":"${GITHUB_PAT_REPO2}"}
        ]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    restart: unless-stopped
```
> Note: If you need complex quotes or escaping, define RUNNERS_MATRIX as a single-line string and/or use Compose variable interpolation with `.env`.

**Each entry:**
- `url`: GitHub org or repo registration URL
- `count`: How many runners for this target
- `labels`: Comma-separated runner labels
- `token`: GitHub token for registration (can reference other env vars)
- `image`: (optional) runner image

## Usage (Single Repo/Org, Legacy)

Alternatively, the old method is still supported with direct environment variables:
- GITHUB_PAT, RUNNER_URL, RUNNER_COUNT, RUNNER_LABELS, RUNNER_IMAGE

## How It Works

On startup, maestro reads the `RUNNERS_MATRIX` JSON env var and dynamically starts/manages all requested runners.

## Building the Maestro Container

The Dockerfile is located in the `src/` folder. To build the image from the repository root directory:

```bash
docker build -t gh-runner-maestro:latest src
```

## Project Structure

- `src/`: Python source for the orchestration service and the Dockerfile
- `requirements.txt`: Python dependencies
- `docker-compose.yml`: Compose file to launch the maestro service

## License

MIT