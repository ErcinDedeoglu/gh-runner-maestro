FROM ubuntu:24.04

# Security: Create non-root user
RUN groupadd -r maestro && useradd -r -g maestro maestro

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install security updates and required packages
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    bash \
    curl \
    python3 \
    python3-venv \
    docker.io \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create virtual environment and install Python dependencies
RUN python3 -m venv /venv
RUN /venv/bin/pip install --no-cache-dir pip setuptools wheel
COPY src/requirements.txt /src/requirements.txt
RUN /venv/bin/pip install --no-cache-dir -r /src/requirements.txt

# Create directories and set permissions
RUN mkdir -p /src /var/log/gh-runner-maestro && \
    chown -R maestro:maestro /src /var/log/gh-runner-maestro /venv && \
    usermod -aG docker maestro

# Copy application code
COPY . /src

WORKDIR /src

# Make entrypoint executable
RUN chmod +x /src/entrypoint.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD /venv/bin/python3 -c "import docker; docker.from_env().ping()" || exit 1

# Install gosu for proper user switching
RUN apt-get update && \
    apt-get install -y --no-install-recommends gosu && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/src/entrypoint.sh"]