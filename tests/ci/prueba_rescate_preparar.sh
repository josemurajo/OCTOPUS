#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# Prepara un Linux (Debian) pequeño de verdad para probar el USB de rescate: es «el ordenador que se ha roto».
# Uso (root): bash tests/ci/prueba_rescate_preparar.sh CARPETA
set -euo pipefail
RAIZ="$1"
if [ ! -x "$RAIZ/usr/sbin/grub-install" ]; then
  debootstrap --variant=minbase \
    --include=linux-image-amd64,grub-efi-amd64-bin,grub-pc-bin,grub2-common,initramfs-tools,systemd-sysv,udev,openssh-client \
    bookworm "$RAIZ" http://deb.debian.org/debian
fi
echo "soy el original" > "$RAIZ/etc/octopus-prueba"
echo "PC-LINUX" > "$RAIZ/etc/hostname"
# consola por el puerto serie: así la prueba ve el arranque sin pantalla
cat > "$RAIZ/etc/default/grub" <<'EOF'
GRUB_DEFAULT=0
GRUB_TIMEOUT=1
GRUB_DISTRIBUTOR=Debian
GRUB_CMDLINE_LINUX_DEFAULT=""
GRUB_CMDLINE_LINUX="console=ttyS0,115200"
GRUB_TERMINAL=serial
GRUB_SERIAL_COMMAND="serial --unit=0 --speed=115200"
EOF
# el fstab del ordenador original (otro disco, que el rescate cambiará)
printf 'UUID=00000000-1111-2222-3333-444444444444 / ext4 errors=remount-ro 0 1\n/swapfile none swap sw 0 0\n' \
  > "$RAIZ/etc/fstab"
# lo que hace que un ordenador sea «ese» y no otro (el despliegue tiene que cambiarlo en cada copia)
printf '127.0.0.1\tlocalhost\n127.0.1.1\tPC-LINUX\n' > "$RAIZ/etc/hosts"
echo "0123456789abcdef0123456789abcdef" > "$RAIZ/etc/machine-id"
rm -f "$RAIZ"/etc/ssh/ssh_host_*; mkdir -p "$RAIZ/etc/ssh"; chroot "$RAIZ" ssh-keygen -A >/dev/null
mkdir -p "$RAIZ/var/lib/octopus" "$RAIZ/etc/octopus"
echo "ayer" > "$RAIZ/var/lib/octopus/ultima_copia.txt"
echo '{"hostname": "PC-LINUX", "agent_token": "el-del-modelo"}' > "$RAIZ/etc/octopus/config.json"
install -m 755 "$(command -v restic)" "$RAIZ/usr/local/bin/restic"
echo "Listo: $RAIZ"
