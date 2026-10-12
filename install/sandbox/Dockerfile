# OCTOPUS - Imagen de la sala de analisis (sandbox)
# Se ejecuta SIEMPRE sin red, solo lectura, sin privilegios (ver lib/incidentes.py)
FROM alpine:3.20
RUN apk add --no-cache file binutils python3 xxd yara unzip coreutils findutils grep
COPY escanear.py reglas.yar /opt/octopus/
USER 65534:65534
WORKDIR /muestras
CMD ["sh"]
