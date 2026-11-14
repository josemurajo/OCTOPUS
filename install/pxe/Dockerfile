# OCTOPUS - Arranque por red (PXE). Lo enciende el panel (Equipos → Arranque por red) y va aparte del servidor.
# Con «proxy DHCP»: NO reparte direcciones (eso lo sigue haciendo el router de siempre), solo les dice a los equipos
# que arrancan por red (F12) dónde está el USB de rescate de OCTOPUS. Necesita la red del anfitrión (Linux).
FROM debian:trixie-slim
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
      dnsmasq xorriso python3 curl ca-certificates iproute2 grub-pc-bin >/dev/null && rm -rf /var/lib/apt/lists/*
COPY octopus_pxe.py /opt/octopus/octopus_pxe.py
VOLUME /srv/octopus-pxe
ENTRYPOINT ["python3", "/opt/octopus/octopus_pxe.py"]
