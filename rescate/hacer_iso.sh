#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# Fabrica la imagen del USB de rescate (octopus-rescate.iso): un Debian pequeño que arranca solo (UEFI y BIOS
# antiguas, desde pendrive o CD), se conecta a la red por cable y abre el programa de rescate de OCTOPUS.
# Todo gratis y de Debian. Lo hace la CI (.github/workflows/rescate-iso.yml); a mano, en Debian/Ubuntu y como root:
#   apt install debootstrap squashfs-tools xorriso grub-pc-bin mtools dosfstools
#   bash rescate/hacer_iso.sh SALIDA.iso [RESTIC]
set -euo pipefail
SALIDA="$(realpath -m "$1")"
RESTIC="${2:-$(command -v restic)}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'umount -lq "$T/raiz/proc" "$T/raiz/sys" "$T/raiz/dev" 2>/dev/null || true' EXIT
R="$T/raiz"

debootstrap --variant=minbase trixie "$R" http://deb.debian.org/debian
mount -t proc proc "$R/proc"; mount --bind /sys "$R/sys"; mount --bind /dev "$R/dev"
echo "deb http://deb.debian.org/debian trixie main non-free-firmware" > "$R/etc/apt/sources.list"
chroot "$R" apt-get update -qq
DEBIAN_FRONTEND=noninteractive chroot "$R" apt-get install -y -qq --no-install-recommends \
  linux-image-amd64 live-boot systemd-sysv udev kmod iproute2 dhcpcd-base ca-certificates \
  python3 python3-cryptography whiptail gdisk parted dosfstools e2fsprogs util-linux ntfs-3g exfatprogs \
  firmware-linux-free firmware-realtek firmware-misc-nonfree shim-signed grub-efi-amd64-signed \
  locales keyboard-configuration console-setup less nano pciutils usbutils busybox >/dev/null

# el programa de rescate y restic
install -d "$R/opt/octopus"
install -m 755 "$AQUI/octopus_rescate.py" "$R/opt/octopus/octopus_rescate.py"
install -m 755 "$RESTIC" "$R/usr/local/bin/restic"
echo "octopus-rescate" > "$R/etc/hostname"
echo "es_ES.UTF-8 UTF-8" > "$R/etc/locale.gen"
chroot "$R" locale-gen >/dev/null
echo 'LANG=es_ES.UTF-8' > "$R/etc/default/locale"
sed -i 's/^XKBLAYOUT=.*/XKBLAYOUT="es"/' "$R/etc/default/keyboard" 2>/dev/null || true

# red por cable con DHCP en cualquier tarjeta
cat > "$R/etc/systemd/system/octopus-red.service" <<'EOF'
[Unit]
Description=OCTOPUS rescate: red por cable
After=systemd-udev-settle.service
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'for i in /sys/class/net/*; do n=$(basename $i); [ "$n" = lo ] && continue; ip link set "$n" up; dhcpcd -b -q "$n"; done'
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
chroot "$R" systemctl enable octopus-red.service >/dev/null

# entra solo como root en la primera pantalla (y en el puerto serie, para las pruebas) y abre el rescate
for tty in getty@tty1 serial-getty@ttyS0; do
  install -d "$R/etc/systemd/system/$tty.service.d"
  cat > "$R/etc/systemd/system/$tty.service.d/octopus.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
EOF
done
cat > "$R/root/.bash_profile" <<'EOF'
echo "OCTOPUS: rescate listo"
sb=$(od -An -t u1 /sys/firmware/efi/efivars/SecureBoot-* 2>/dev/null | awk '{print $NF}')
[ "$sb" = 1 ] && echo "OCTOPUS: arranque seguro encendido"
srv=$(tr ' ' '\n' < /proc/cmdline | sed -n 's/^octopus.servidor=//p')
[ -n "$srv" ] && echo "OCTOPUS: arrancado por red desde $srv"
if grep -q octopus.prueba /proc/cmdline; then
  python3 /opt/octopus/octopus_rescate.py version; restic version; exit 0
fi
python3 /opt/octopus/octopus_rescate.py
echo; echo "Escribe  reboot  para reiniciar o  python3 /opt/octopus/octopus_rescate.py  para volver a empezar."
EOF
chroot "$R" passwd -d root >/dev/null
chroot "$R" apt-get clean
rm -rf "$R/var/lib/apt/lists/"* "$R/var/cache/apt/"*
umount -lq "$R/proc" "$R/sys" "$R/dev"

# la imagen: núcleo + initrd + sistema comprimido.
# Arranque: UEFI con el shim y el GRUB FIRMADOS de Debian (funciona con «Arranque seguro» encendido, como viene casi
# todo PC) y BIOS antigua con GRUB. Es «híbrida»: vale grabada en pendrive (Rufus, balenaEtcher) o en CD.
I="$T/iso"
install -d "$I/live" "$I/boot/grub" "$I/.disk"
echo "OCTOPUS rescate" > "$I/.disk/info"
cp "$R"/boot/vmlinuz-* "$I/live/vmlinuz"
cp "$R"/boot/initrd.img-* "$I/live/initrd.img"
mksquashfs "$R" "$I/live/filesystem.squashfs" -comp xz -e boot -noappend -quiet
cat > "$I/boot/grub/grub.cfg" <<'EOF'
if serial --unit=0 --speed=115200; then
  terminal_input console serial
  terminal_output console serial
fi
set timeout=3
menuentry "OCTOPUS - USB de rescate" {
  linux /live/vmlinuz boot=live components quiet locales=es_ES.UTF-8 keyboard-layouts=es console=ttyS0,115200 console=tty0
  initrd /live/initrd.img
}
menuentry "OCTOPUS - USB de rescate (modo seguro: si la pantalla se queda negra)" {
  linux /live/vmlinuz boot=live components nomodeset locales=es_ES.UTF-8 keyboard-layouts=es
  initrd /live/initrd.img
}
EOF
# UEFI: una pequeña partición FAT con shim (BOOTX64.EFI) y el GRUB firmado para CD/USB, que busca /.disk/info
EFI="$T/efi.img"
dd if=/dev/zero of="$EFI" bs=1M count=8 status=none
mkfs.vfat -n OCTOEFI "$EFI" >/dev/null
mmd -i "$EFI" ::/EFI ::/EFI/BOOT ::/EFI/debian
mcopy -i "$EFI" "$R/usr/lib/shim/shimx64.efi.signed" ::/EFI/BOOT/BOOTX64.EFI
mcopy -i "$EFI" "$R/usr/lib/grub/x86_64-efi-signed/gcdx64.efi.signed" ::/EFI/BOOT/grubx64.efi
printf 'search --file --set=root /.disk/info\nset prefix=($root)/boot/grub\nconfigfile $prefix/grub.cfg\n' > "$T/stub.cfg"
mcopy -i "$EFI" "$T/stub.cfg" ::/EFI/debian/grub.cfg
mcopy -i "$EFI" "$T/stub.cfg" ::/EFI/BOOT/grub.cfg
# Arranque por red (lo usa el servidor, install/pxe): shim y el GRUB firmado para red (UEFI, también con arranque
# seguro). El GRUB para BIOS antiguas y el grub.cfg con su dirección los pone el propio servidor.
install -d "$I/pxe"
cp "$R/usr/lib/shim/shimx64.efi.signed" "$I/pxe/bootx64.efi"
cp "$R/usr/lib/grub/x86_64-efi-signed/grubnetx64.efi.signed" "$I/pxe/grubx64.efi"
# BIOS antigua
grub-mkimage -O i386-pc-eltorito -p /boot/grub -o "$I/boot/grub/eltorito.img" \
  biosdisk iso9660 part_msdos part_gpt normal configfile linux search search_fs_file serial terminal echo test true \
  all_video
xorriso -as mkisofs -iso-level 3 -V OCTOPUS_RESCATE -J -joliet-long -R -o "$SALIDA" \
  -b boot/grub/eltorito.img -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
  --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img \
  -append_partition 2 0xef "$EFI" -appended_part_as_gpt \
  -eltorito-alt-boot -e --interval:appended_partition_2:all:: -no-emul-boot \
  "$I" 2>&1 | tail -2
ls -la "$SALIDA"
sha256sum "$SALIDA" | awk '{print $1}' > "$SALIDA.sha256"
