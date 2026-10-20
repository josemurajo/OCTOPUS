# OCTOPUS Zero-Touch - imagen del servidor (panel, API, almacen de copias y mantenimiento)
# La construye el instalador:  docker compose -f install/docker-compose.yml build
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${PYTHON_IMAGE}
ARG TARGETARCH
ARG RESTIC_VERSION=0.16.4
ARG REST_SERVER_VERSION=0.13.0
ARG DOCKER_CLI_VERSION=27.3.1
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    OCTOPUS_EN_CONTENEDOR=1 OCTOPUS_DATA=/data OCTOPUS_BOVEDA_DIR=/boveda OCTOPUS_SANDBOX_DIR=/data/sandbox \
    RESTIC_CACHE_DIR=/data/.cache/restic TZ=Europe/Madrid

RUN apt-get update && apt-get install -y --no-install-recommends \
        iproute2 iputils-ping procps openssh-client sshpass \
        p7zip-full file binutils yara curl bzip2 ca-certificates openssl tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; arch="${TARGETARCH:-amd64}"; \
    case "$arch" in amd64) darch=x86_64 ;; arm64) darch=aarch64 ;; *) echo "arquitectura no soportada: $arch"; exit 1 ;; esac; \
    curl -fsSL "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_${arch}.bz2" \
        | bunzip2 > /usr/local/bin/restic; \
    curl -fsSL "https://github.com/restic/rest-server/releases/download/v${REST_SERVER_VERSION}/rest-server_${REST_SERVER_VERSION}_linux_${arch}.tar.gz" \
        | tar -xz --strip-components=1 -C /usr/local/bin "rest-server_${REST_SERVER_VERSION}_linux_${arch}/rest-server"; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${darch}/docker-${DOCKER_CLI_VERSION}.tgz" \
        | tar -xz --strip-components=1 -C /usr/local/bin docker/docker; \
    chmod 755 /usr/local/bin/restic /usr/local/bin/rest-server /usr/local/bin/docker; \
    restic version; rest-server --version; docker --version

COPY requirements.txt /app/requirements.txt
# ansible-core ya no va en la imagen (~100 MB): ansible/desplegar.sh lo instala la primera vez que se usa
RUN pip install -r /app/requirements.txt

COPY . /app
# Todo lo que cambia (configuracion, claves, base de datos, tunel) vive en el volumen /data
RUN set -eux; cd /app; rm -rf data logs ansible/config.json ansible/equipos.ini .env .venv; \
    ln -s /data/panel data; ln -s /data/logs logs; \
    ln -s /data/ansible/config.json ansible/config.json; ln -s /data/ansible/equipos.ini ansible/equipos.ini; \
    ln -s /data/.env .env; \
    rm -rf /root/.ssh; ln -s /data/ssh /root/.ssh; \
    python -m compileall -q lib

WORKDIR /app
EXPOSE 8080 8000
VOLUME ["/data", "/boveda"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsk https://127.0.0.1:8080/healthz >/dev/null || curl -fs http://127.0.0.1:8080/healthz >/dev/null || exit 1
STOPSIGNAL SIGTERM
ENTRYPOINT ["python", "/app/lib/servidor.py"]
