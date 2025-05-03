FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        bash \
        curl \
        docker.io \
        python3 \
        python3-venv \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /venv
RUN /venv/bin/pip install --no-cache-dir pip
COPY requirements.txt /src/requirements.txt
RUN /venv/bin/pip install --no-cache-dir -r /src/requirements.txt

ENV PATH="/venv/bin:$PATH"

COPY . /src/

WORKDIR /src

ENTRYPOINT ["python", "-u", "main.py"]