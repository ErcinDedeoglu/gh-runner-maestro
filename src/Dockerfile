FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    curl \
    python3 \
    python3-venv \
    docker.io \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /venv
RUN /venv/bin/pip install --no-cache-dir pip
COPY requirements.txt /src/requirements.txt
RUN /venv/bin/pip install --no-cache-dir -r /src/requirements.txt

COPY . /src/

WORKDIR /src

COPY entrypoint.sh /src/entrypoint.sh
RUN chmod +x /src/entrypoint.sh

ENTRYPOINT ["/src/entrypoint.sh"]