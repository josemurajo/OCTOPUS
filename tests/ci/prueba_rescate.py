#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
Prueba del USB de rescate (rescate/octopus_rescate.py y el panel).

  python tests/ci/prueba_rescate.py unidad
      código de un solo uso, cifrado, fstab, y el panel de verdad: da el código, el USB lo cambia por la
      configuración del equipo una sola vez, y un código malo no vale.
  sudo python tests/ci/prueba_rescate.py disco RAIZ_DE_UN_LINUX [--arrancar]
      (Linux, root) hace una «copia completa» de RAIZ con restic, la pone con el rescate en un disco de mentira
      (archivo + /dev/loop), y comprueba particiones, archivos, fstab y GRUB. Con --arrancar, además arranca ese disco
      en una máquina virtual (QEMU, UEFI) y espera a que salga «login:».
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ_REPO / "rescate"))
import octopus_rescate as r  # noqa: E402

F = []


def chk(c, n, x=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else x)
    if not c:
        F.append(n)


def unidad():
    c = r.nuevo_codigo()
    chk(len(c) == 14 and c.count("-") == 2 and r.normalizar(c), "código de 12 letras y números en tres grupos", c)
    chk(r.normalizar(c.lower().replace("-", " ")) == c.replace("-", ""), "da igual mayúsculas, espacios o guiones")
    chk(not r.normalizar("ABCD-EFGH-IJK0") and not r.normalizar("ABC"), "un código mal escrito no vale")
    datos = {"hostname": "PC-ANA", "password_restic": "x"}
    t = r.cifrar(c, datos)
    chk(r.descifrar(c, t) == datos and "PC-ANA" not in t, "lo que viaja va cifrado con el código")
    try:
        r.descifrar(r.nuevo_codigo(), t)
        chk(False, "con otro código no se puede leer")
    except Exception:
        chk(True, "con otro código no se puede leer")
    chk(r.identificador(c) != r.identificador(r.nuevo_codigo()) and len(r.identificador(c)) == 64,
        "el servidor reconoce el código sin que viaje")
    fst = r.arreglar_fstab("# comentario\nUUID=aaa / ext4 defaults 0 1\nUUID=bbb /boot/efi vfat umask=0077 0 1\n"
                           "/swapfile none swap sw 0 0\nUUID=ccc /datos ext4 defaults 0 2\n", "NUEVA", "EFI1")
    lineas = fst.splitlines()
    chk("UUID=NUEVA / ext4 errors=remount-ro 0 1" in lineas and "UUID=EFI1 /boot/efi vfat umask=0077 0 1" in lineas,
        "fstab: la raíz y el arranque, en el disco nuevo", fst)
    chk("# (antes) UUID=aaa / ext4 defaults 0 1" in lineas and "# (antes) /swapfile none swap sw 0 0" in lineas
        and "# comentario" in lineas, "fstab: lo viejo queda comentado", fst)
    chk(any(l.startswith("UUID=ccc") and "nofail" in l for l in lineas), "fstab: otros discos con nofail", fst)
    chk(r.particion("/dev/sda", 3) == "/dev/sda3" and r.particion("/dev/nvme0n1", 1) == "/dev/nvme0n1p1"
        and r.particion("/dev/loop7", 1) == "/dev/loop7p1", "nombres de las particiones")

    # el panel de verdad
    tmp = tempfile.mkdtemp()
    ans = Path(tmp) / "ansible"
    ans.mkdir()
    (ans / "config.json").write_text(json.dumps({"servidor": "https://10.0.0.1", "password_restic": "secreto",
                                                 "ip_cerebro": "10.0.0.1"}), encoding="utf-8")
    os.environ.update(DB_PATH=os.path.join(tmp, "p.db"), OCTOPUS_DATA=os.path.join(tmp, "data"),
                      ADMIN_PASSWORD="ClaveInicialDePrueba-123", PANEL_HTTPS="0", OCTOPUS_ANSIBLE_DIR=str(ans),
                      OCTOPUS_BOVEDA_DIR=os.path.join(tmp, "boveda"))
    sys.path.insert(0, str(RAIZ_REPO / "lib"))
    import admin_panel as a
    import re
    a.app.config.update(TESTING=True)
    cl = a.app.test_client()

    def tok(h):
        m = re.search(r'name="csrf_token" value="([^"]+)"', h)
        return m.group(1) if m else ""
    cl.post("/login", data={"csrf_token": tok(cl.get("/login").get_data(as_text=True)), "username": "admin",
                            "password": "ClaveInicialDePrueba-123"})
    nueva = "OtraClaveSegura-2026!"
    cl.post("/cuenta/contrasena", data={"csrf_token": tok(cl.get("/cuenta/contrasena").get_data(as_text=True)),
                                        "actual": "ClaveInicialDePrueba-123", "nueva": nueva, "repetir": nueva})
    cl.post("/bienvenida", data={"csrf_token": tok(cl.get("/bienvenida").get_data(as_text=True)), "modo": "casa"})
    usb = a.app.test_client()   # el pendrive no tiene sesión en el panel
    with a.get_db_connection() as cx:
        cx.execute("INSERT INTO systems (hostname, ip_address, os_family, status, notes) VALUES ('PC-LINUX', "
                   "'10.0.0.5', 'linux', 'unknown', '{}')")
        sid = cx.execute("SELECT id FROM systems WHERE hostname='PC-LINUX'").fetchone()[0]
    chk(cl.get(f"/equipos/{sid}/rescate").status_code == 302, "en pruebas y apagado: no se abre")
    a.config_manager.set_config("usb_rescate", True)
    h = cl.get(f"/equipos/{sid}/rescate").get_data(as_text=True)
    chk("Dar código" in h and "octopus-rescate.iso" in h and "Rufus" in h, "pantalla del USB de rescate", h[:300])
    h = cl.post(f"/equipos/{sid}/rescate", data={"csrf_token": tok(h)}).get_data(as_text=True)
    m = re.search(r"<code>([A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4})</code>", h)
    chk(bool(m) and "https://10.0.0.1" in h, "da un código y la dirección del servidor", h[-800:])
    codigo = m.group(1) if m else "AAAA-AAAA-AAAA"
    resp = usb.post("/api/rescate", json={"id": r.identificador(codigo)})
    cfg = r.descifrar(codigo, resp.get_json()["datos"]) if resp.status_code == 200 else {}
    chk(cfg.get("hostname") == "PC-LINUX" and cfg.get("password_restic") == "secreto" and cfg.get("os_family") == "linux"
        and "agent_token" not in cfg, "el USB recibe cómo llegar a las copias de ESE equipo", (resp.status_code, cfg))
    chk(usb.post("/api/rescate", json={"id": r.identificador(codigo)}).status_code == 403, "el código vale una sola vez")
    chk(usb.post("/api/rescate", json={"id": r.identificador(r.nuevo_codigo())}).status_code == 403,
        "un código inventado no vale")
    chk(usb.post("/api/rescate", json={"id": "'; drop table"}).status_code == 400, "basura: no")
    h = cl.post(f"/equipos/{sid}/rescate", data={"csrf_token": tok(cl.get(f"/equipos/{sid}/rescate").get_data(as_text=True))}).get_data(as_text=True)
    c2 = re.search(r"<code>([A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4})</code>", h).group(1)
    with a.get_db_connection() as cx:
        cx.execute("UPDATE rescate_codigos SET expira = ?", (time.time() - 1,))
    chk(usb.post("/api/rescate", json={"id": r.identificador(c2)}).status_code == 403, "pasada la hora, no vale")
    with a.get_db_connection() as cx:
        quedan = cx.execute("SELECT COUNT(*) FROM rescate_codigos WHERE datos IS NOT NULL AND usado = 1").fetchone()[0]
    chk(quedan == 0, "lo usado no se guarda")
    # desplegar en varios equipos: un código para toda la tanda; cada ordenador sale con su nombre y su clave
    import datetime as _dt
    with a.get_db_connection() as cx:
        cx.execute("UPDATE systems SET notes = ? WHERE id = ?", (json.dumps({"rutas": ["/home"]}), sid))
    a._copia_completa_mas_nueva = lambda row: {"id": "abcd1234", "time": _dt.datetime(2026, 11, 1, 10, 0)}
    chk(cl.get("/despliegue").status_code == 302, "despliegue: apagado, no se abre")
    a.config_manager.set_config("despliegue_masa", True)
    h = cl.get("/despliegue").get_data(as_text=True)
    chk("PC-LINUX" in h and "Dar código del despliegue" in h, "pantalla del despliegue con los equipos Linux")
    h = cl.post("/despliegue", data={"csrf_token": tok(h), "ref": str(sid), "prefijo": "aula 1", "cuantos": "2",
                                     "horas": "8"}).get_data(as_text=True)
    m = re.search(r"<code>([A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4})</code>", h)
    chk(bool(m), "da el código de la tanda", h[-600:])
    cod = m.group(1) if m else "AAAA-AAAA-AAAA"
    nombres = []
    for mac in ("52:54:00:12:3f:2a", "52:54:00:aa:bb:cc"):
        rr = usb.post("/api/rescate", json={"id": r.identificador(cod), "mac": mac})
        dd = r.descifrar(cod, rr.get_json()["datos"]) if rr.status_code == 200 else {}
        nuevo = (dd.get("despliegue") or {}).get("nuevo") or {}
        nombres.append(nuevo.get("hostname"))
        ok_tok = bool(nuevo.get("agente", {}).get("agent_token")) and a._ordenes.autenticar(
            nuevo.get("hostname"), nuevo.get("agente", {}).get("agent_token")) is not None
        chk(dd.get("despliegue", {}).get("copia") == "abcd1234" and dd.get("hostname") == "PC-LINUX" and ok_tok
            and nuevo.get("agente", {}).get("backup_paths") == ["/home"],
            f"el ordenador {mac} recibe el sistema del modelo y su propia clave de OCTOPUS", dd)
    chk(nombres == ["AULA1-3F2A", "AULA1-BBCC"], "cada uno con su nombre", nombres)
    with a.get_db_connection() as cx:
        altas = [x[0] for x in cx.execute("SELECT hostname FROM systems WHERE hostname LIKE 'AULA1-%'")]
    chk(sorted(altas) == ["AULA1-3F2A", "AULA1-BBCC"], "aparecen solos en el panel", altas)
    chk(usb.post("/api/rescate", json={"id": r.identificador(cod), "mac": "52:54:00:00:00:01"}).status_code == 403,
        "pasado el máximo de la tanda, no vale")
    h = cl.get("/despliegue").get_data(as_text=True)
    chk("2 de 2" in h and "AULA1-3F2A" in h, "se ve cómo va la tanda")

    # arranque por red: la pantalla (aquí no hay Docker: tiene que decirlo claro)
    chk(cl.get("/arranque-red").status_code == 302, "arranque por red: apagado, no se abre")
    a.config_manager.set_config("arranque_red", True)
    h = cl.get("/arranque-red").get_data(as_text=True)
    chk("Arranque por red" in h and ("Docker" in h or "OCTOPUS_IP" in h or "Encender" in h), "pantalla del arranque por red",
        h[-600:])
    chk("Arranque por red" in cl.get("/equipos").get_data(as_text=True), "botón en Equipos")


def _sh(*cmd, **k):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **k)


def disco(fuente, arrancar=False):
    tmp = Path(tempfile.mkdtemp(prefix="rescate_"))
    repo = tmp / "almacen"
    cfg = {"hostname": "PC-LINUX", "password_restic": "prueba-rescate", "restic_repository": str(repo),
           "os_family": "linux"}
    env = r.entorno(cfg)
    _sh(r._restic(), "init", env=env)
    excl = ["/proc", "/sys", "/dev", "/run", "/tmp", "/var/tmp", "/var/cache"]
    # la copia se hace como el agente (copia completa): con la raíz del sistema en «/». Para eso, desde dentro.
    _sh("mount", "--bind", str(repo.parent), os.path.join(fuente, "mnt"))
    try:
        ok = subprocess.run(["chroot", fuente, "/usr/local/bin/restic", "backup", "/", "--tag", "octopus-agent",
                             "--tag", "completa", "--host", "PC-LINUX", "--one-file-system",
                             *[x for e in excl for x in ("--exclude", e)], "--exclude", "/mnt"],
                            env={**env, "RESTIC_REPOSITORY": "/mnt/almacen", "RESTIC_CACHE_DIR": "/root/.cache/restic",
                                 "PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}, capture_output=True, text=True)
    finally:
        subprocess.run(["umount", os.path.join(fuente, "mnt")])
    chk(ok.returncode == 0, "copia completa del Linux de prueba", ok.stderr[-500:])
    lista = r.copias(cfg, completas=True)
    chk(len(lista) == 1 and lista[0]["completa"], "el rescate ve la copia completa", lista)
    imagen = tmp / "disco.img"
    with open(imagen, "wb") as fh:
        fh.truncate(6 * 1024 ** 3)
    loop = _sh("losetup", "--show", "-f", "-P", str(imagen)).stdout.strip()
    try:
        res = r.restaurar_linux(cfg, lista[0]["id"], loop)
        chk(res["status"] == "success" and "UEFI" in res["arranque"] and "BIOS" in res["arranque"],
            "pone la copia y el arranque UEFI y BIOS", res)
        tipos = [subprocess.run(["blkid", "-p", "-s", "TYPE", "-o", "value", r.particion(loop, n)], capture_output=True,
                                text=True).stdout.strip() for n in (1, 2, 3)]
        chk(tipos == ["vfat", "", "ext4"] and os.path.exists(r.particion(loop, 2)), "particiones: EFI, BIOS y el sistema",
            tipos)
        m = tempfile.mkdtemp()
        _sh("mount", r.particion(loop, 3), m)
        _sh("mount", r.particion(loop, 1), m + "/boot/efi")
        try:
            chk(Path(m, "etc/octopus-prueba").read_text().strip() == "soy el original", "los archivos están")
            chk(oct(Path(m, "tmp").stat().st_mode)[-4:] == "1777", "carpetas del sistema recreadas")
            fst = Path(m, "etc/fstab").read_text()
            chk(f"UUID={r._uuid(r.particion(loop, 3))} / ext4" in fst, "fstab apunta al disco nuevo", fst)
            chk(Path(m, "boot/efi/EFI/BOOT/BOOTX64.EFI").is_file(), "GRUB para UEFI en su sitio (vale en cualquier placa)")
            cfgg = Path(m, "boot/grub/grub.cfg").read_text()
            chk(r._uuid(r.particion(loop, 3)) in cfgg, "GRUB arranca el disco nuevo")
        finally:
            subprocess.run(["umount", "-R", m])
        try:
            r.restaurar_linux(cfg, lista[0]["id"], "/dev/no-existe")
            chk(False, "un disco que no existe: no")
        except RuntimeError:
            chk(True, "un disco que no existe: no")
    finally:
        subprocess.run(["losetup", "-d", loop])
    # despliegue: la misma copia como OTRO ordenador
    viejas = {f.name: f.read_bytes() for f in Path(fuente, "etc/ssh").glob("ssh_host_*_key")}
    loop = _sh("losetup", "--show", "-f", "-P", str(imagen)).stdout.strip()
    try:
        r.restaurar_linux(cfg, lista[0]["id"], loop, nuevo={"hostname": "AULA-3F2A",
                                                            "agente": {"hostname": "AULA-3F2A", "agent_token": "suyo"}})
        m = tempfile.mkdtemp()
        _sh("mount", r.particion(loop, 3), m)
        try:
            chk(Path(m, "etc/hostname").read_text().strip() == "AULA-3F2A" and "AULA-3F2A" in Path(m, "etc/hosts").read_text()
                and "PC-LINUX" not in Path(m, "etc/hosts").read_text(), "despliegue: nombre nuevo")
            chk(Path(m, "etc/machine-id").read_text() == "", "despliegue: identidad de máquina nueva (se crea al arrancar)")
            nuevas = {f.name: f.read_bytes() for f in Path(m, "etc/ssh").glob("ssh_host_*_key")}
            chk(nuevas and all(nuevas.get(k) != v for k, v in viejas.items()), "despliegue: claves SSH propias",
                list(nuevas))
            chk(json.loads(Path(m, "etc/octopus/config.json").read_text())["agent_token"] == "suyo"
                and not Path(m, "var/lib/octopus/ultima_copia.txt").exists(), "despliegue: su propio OCTOPUS")
            chk(Path(m, "etc/octopus-prueba").read_text().strip() == "soy el original", "despliegue: con todo lo del modelo")
        finally:
            subprocess.run(["umount", m])
    finally:
        subprocess.run(["losetup", "-d", loop])
    sacado = r.sacar_archivos(cfg, lista[0]["id"], str(tmp / "usb"))
    chk(Path(sacado["carpeta"], "etc/octopus-prueba").is_file(), "sacar los archivos a un disco USB")
    if arrancar:
        arrancar_disco(imagen)
    shutil.rmtree(tmp, ignore_errors=True)


def arrancar_disco(imagen):
    pares = [("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
             ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd")]
    code, vars_ = next((c, v) for c, v in pares if os.path.exists(c) and os.path.exists(v))
    mis_vars = str(Path(imagen).with_name("vars.fd"))
    shutil.copy(vars_, mis_vars)
    kvm = ["-enable-kvm", "-cpu", "host"] if os.access("/dev/kvm", os.W_OK) else []
    cmd = ["qemu-system-x86_64", "-m", "1024", "-nographic", "-no-reboot", *kvm, "-machine", "q35",
           "-drive", f"if=pflash,format=raw,readonly=on,file={code}", "-drive", f"if=pflash,format=raw,file={mis_vars}",
           "-drive", f"file={imagen},format=raw,if=virtio"]
    print("Arrancando:", " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    salida, fin = b"", time.time() + (300 if kvm else 900)
    os.set_blocking(p.stdout.fileno(), False)
    while time.time() < fin and b"login:" not in salida:
        trozo = p.stdout.read(65536)
        if trozo:
            salida += trozo
        elif p.poll() is not None:
            break
        else:
            time.sleep(1)
    p.kill()
    texto = salida.decode(errors="replace")
    chk("login:" in texto, "el disco puesto por el rescate ARRANCA (UEFI) hasta «login:»", texto[-1500:])


if __name__ == "__main__":
    if sys.argv[1:2] == ["unidad"]:
        unidad()
    elif sys.argv[1:2] == ["disco"]:
        disco(sys.argv[2], arrancar="--arrancar" in sys.argv)
    else:
        print(__doc__)
        sys.exit(2)
    print("FALLOS:", F or "ninguno")
    sys.exit(1 if F else 0)
