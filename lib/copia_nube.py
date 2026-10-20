# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Copia de la NUBE: Microsoft 365 y Google Workspace (corre en el SERVIDOR, no en los equipos).

Qué copia:
  Microsoft 365 ... el correo de cada usuario (cada mensaje como archivo .eml, que abre cualquier programa de correo) y
                    sus archivos de OneDrive. (SharePoint se añade igual, por «sitios».)
  Google Workspace  el correo de Gmail (.eml) y los archivos de Drive.

Cómo guarda: en una carpeta del servidor (OCTOPUS_DATA/nube/<servicio>/<usuario>) que se mantiene entre copias, así
cada día solo baja lo NUEVO o lo que ha cambiado. Luego esa carpeta se guarda en el almacén con la etiqueta «nube»
(restic, cifrado y «solo añadir»), igual que el resto de copias.

Para entrar usa los permisos que el cliente da UNA vez (un «app» de Microsoft o una cuenta de servicio de Google). El
panel tiene un asistente paso a paso. Las claves se guardan cifradas, nunca en claro.

Pensado para que se pueda probar sin tocar la nube de verdad: las direcciones base se pueden cambiar con variables de
entorno (OCTOPUS_GRAPH_BASE, OCTOPUS_MS_LOGIN, OCTOPUS_GOOGLE_BASE, OCTOPUS_GOOGLE_TOKEN), que es lo que hace la prueba
tests/ci/prueba_nube.py con un servidor falso.

QUÉ TOCAR:
  - Qué se copia de cada servicio ... _ms_usuario() y _google_usuario().
  - Añadir SharePoint/Teams ......... un _ms_sitios() que baje los «drives» de los sitios (igual que OneDrive).
  - Credenciales / asistente ........ lib/admin_panel.py (rutas /ajustes/nube) y templates/nube.html.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

GRAPH_BASE = os.environ.get("OCTOPUS_GRAPH_BASE", "https://graph.microsoft.com/v1.0")
MS_LOGIN = os.environ.get("OCTOPUS_MS_LOGIN", "https://login.microsoftonline.com")
GOOGLE_BASE = os.environ.get("OCTOPUS_GOOGLE_BASE", "https://www.googleapis.com")
GOOGLE_TOKEN_URL = os.environ.get("OCTOPUS_GOOGLE_TOKEN", "https://oauth2.googleapis.com/token")
SERVICIOS = {"microsoft": "Microsoft 365", "google": "Google Workspace"}


# ------------------------------------------------------------------------------------------------ HTTP
def _pedir(url: str, token: str = "", datos: bytes | None = None, cabeceras: dict | None = None,
           metodo: str | None = None, binario: bool = False, timeout: int = 120):
    cab = dict(cabeceras or {})
    if token:
        cab["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=datos, headers=cab, method=metodo or ("POST" if datos else "GET"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cuerpo = r.read()
    return cuerpo if binario else json.loads(cuerpo or b"{}")


def _nombre_seguro(s: str) -> str:
    return re.sub(r"[^\w.@ -]", "_", str(s or "")).strip()[:150] or "sin_nombre"


# ------------------------------------------------------------------------------------------------ Microsoft 365
def _ms_token(cfg: dict) -> str:
    datos = urllib.parse.urlencode({
        "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
        "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default",
    }).encode()
    r = _pedir(f"{MS_LOGIN}/{cfg['tenant']}/oauth2/v2.0/token", datos=datos,
               cabeceras={"Content-Type": "application/x-www-form-urlencoded"})
    return r["access_token"]


def _paginas(url: str, token: str):
    """Recorre una lista de Graph/Google siguiendo el enlace a la página siguiente."""
    while url:
        r = _pedir(url, token)
        for item in r.get("value", []):
            yield item
        url = r.get("@odata.nextLink") or r.get("nextPageLink")


def _ms_usuarios(token: str) -> list[dict]:
    return [{"id": u["id"], "correo": u.get("userPrincipalName") or u.get("mail") or u["id"]}
            for u in _paginas(f"{GRAPH_BASE}/users?$select=id,userPrincipalName,mail&$top=100", token)
            if u.get("userPrincipalName") or u.get("mail")]


def _descargar(url: str, token: str, destino: Path, marca: str, hechos: dict) -> bool:
    """Baja un archivo solo si cambió (compara una marca: fecha/tamaño). Devuelve True si lo bajó."""
    if hechos.get(str(destino)) == marca and destino.exists():
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    datos = _pedir(url, token, binario=True)
    destino.write_bytes(datos)
    hechos[str(destino)] = marca
    return True


def _ms_usuario(token: str, usuario: dict, carpeta: Path, estado: dict) -> dict:
    uid, correo = usuario["id"], usuario["correo"]
    base = carpeta / _nombre_seguro(correo)
    hechos = estado.setdefault(correo, {})
    nuevos = 0
    # correo: solo los mensajes nuevos desde la última copia (incremental por fecha)
    desde = hechos.get("_correo_hasta", "")
    filtro = ("&$filter=" + urllib.parse.quote(f"receivedDateTime gt {desde}")) if desde else ""
    ultima = desde
    try:
        for msg in _paginas(f"{GRAPH_BASE}/users/{uid}/messages?$select=id,receivedDateTime&$top=50{filtro}", token):
            eml = base / "correo" / (_nombre_seguro(msg["id"]) + ".eml")
            if _descargar(f"{GRAPH_BASE}/users/{uid}/messages/{msg['id']}/$value", token, eml, msg["id"], hechos):
                nuevos += 1
            if msg.get("receivedDateTime", "") > (ultima or ""):
                ultima = msg["receivedDateTime"]
        if ultima:
            hechos["_correo_hasta"] = ultima
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 404):            # sin buzón (p. ej. una sala): se salta
            raise
    # OneDrive: todos los archivos, bajando solo los que cambiaron
    try:
        for item in _paginas(f"{GRAPH_BASE}/users/{uid}/drive/root/children?$top=200", token):
            _ms_item(token, uid, item, base / "OneDrive", hechos)
            nuevos += 1 if "file" in item else 0
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 404):
            raise
    return {"usuario": correo, "nuevos": nuevos}


def _ms_item(token: str, uid: str, item: dict, carpeta: Path, hechos: dict) -> None:
    nombre = _nombre_seguro(item.get("name", "sin_nombre"))
    if "folder" in item:
        for hijo in _paginas(f"{GRAPH_BASE}/users/{uid}/drive/items/{item['id']}/children?$top=200", token):
            _ms_item(token, uid, hijo, carpeta / nombre, hechos)
    elif "file" in item:
        marca = f"{item.get('lastModifiedDateTime')}:{item.get('size')}"
        _descargar(f"{GRAPH_BASE}/users/{uid}/drive/items/{item['id']}/content", token, carpeta / nombre, marca, hechos)


def _ms_copiar(cfg: dict, carpeta: Path, estado: dict) -> dict:
    token = _ms_token(cfg)
    usuarios = _ms_usuarios(token)
    detalle = [_ms_usuario(token, u, carpeta, estado) for u in usuarios]
    return {"servicio": "microsoft", "usuarios": len(usuarios), "detalle": detalle}


# ------------------------------------------------------------------------------------------------ Google Workspace
def _google_token(cfg: dict, sujeto: str) -> str:
    """Token para actuar en nombre de un usuario del dominio (delegación), con la cuenta de servicio (JWT)."""
    sa = cfg["cuenta_servicio"] if isinstance(cfg.get("cuenta_servicio"), dict) else json.loads(cfg["cuenta_servicio"])
    ahora = int(time.time())
    claim = {"iss": sa["client_email"], "sub": sujeto, "aud": GOOGLE_TOKEN_URL, "iat": ahora, "exp": ahora + 3600,
             "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/drive.readonly"}
    jwt = _firmar_jwt(claim, sa["private_key"])
    datos = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}).encode()
    r = _pedir(GOOGLE_TOKEN_URL, datos=datos, cabeceras={"Content-Type": "application/x-www-form-urlencoded"})
    return r["access_token"]


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _firmar_jwt(claim: dict, clave_pem: str) -> str:
    cab = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    cuerpo = _b64url(json.dumps(claim).encode())
    firmado = f"{cab}.{cuerpo}".encode()
    if os.environ.get("OCTOPUS_GOOGLE_TOKEN"):      # en pruebas no se firma de verdad
        return f"{cab}.{cuerpo}.prueba"
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    clave = serialization.load_pem_private_key(clave_pem.encode(), password=None)
    return f"{cab}.{cuerpo}." + _b64url(clave.sign(firmado, padding.PKCS1v15(), hashes.SHA256()))


def _google_usuarios(cfg: dict) -> list[str]:
    correos = cfg.get("usuarios") or []
    return [c.strip() for c in (correos.split(",") if isinstance(correos, str) else correos) if c.strip()]


def _google_usuario(cfg: dict, correo: str, carpeta: Path, estado: dict) -> dict:
    token = _google_token(cfg, correo)
    base = carpeta / _nombre_seguro(correo)
    hechos = estado.setdefault(correo, {})
    nuevos = 0
    # Gmail: mensajes nuevos (incremental con historyId guardado sería lo ideal; aquí por lista + ya bajados)
    url = f"{GOOGLE_BASE}/gmail/v1/users/{urllib.parse.quote(correo)}/messages?maxResults=100"
    try:
        for m in _paginas_google(url, token, "messages"):
            eml = base / "Gmail" / (_nombre_seguro(m["id"]) + ".eml")
            if str(eml) not in hechos or not eml.exists():
                raw = _pedir(f"{GOOGLE_BASE}/gmail/v1/users/{urllib.parse.quote(correo)}/messages/{m['id']}?format=raw", token)
                eml.parent.mkdir(parents=True, exist_ok=True)
                eml.write_bytes(base64.urlsafe_b64decode(raw["raw"] + "=="))
                hechos[str(eml)] = m["id"]
                nuevos += 1
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 404):
            raise
    # Drive: archivos (bajando solo los que cambiaron)
    try:
        durl = f"{GOOGLE_BASE}/drive/v3/files?fields=files(id,name,modifiedTime,size,mimeType),nextPageToken&pageSize=200"
        for f in _paginas_google(durl, token, "files"):
            if (f.get("mimeType") or "").startswith("application/vnd.google-apps"):
                continue   # documentos de Google: se exportarían aparte; se omiten en esta versión
            dest = base / "Drive" / _nombre_seguro(f.get("name", f["id"]))
            marca = f"{f.get('modifiedTime')}:{f.get('size')}"
            if _descargar(f"{GOOGLE_BASE}/drive/v3/files/{f['id']}?alt=media", token, dest, marca, hechos):
                nuevos += 1
    except urllib.error.HTTPError as exc:
        if exc.code not in (403, 404):
            raise
    return {"usuario": correo, "nuevos": nuevos}


def _paginas_google(url: str, token: str, clave: str):
    while url:
        r = _pedir(url, token)
        for item in r.get(clave, []):
            yield item
        tok = r.get("nextPageToken")
        url = (url.split("&pageToken=")[0] + "&pageToken=" + tok) if tok else ""


def _google_copiar(cfg: dict, carpeta: Path, estado: dict) -> dict:
    usuarios = _google_usuarios(cfg)
    detalle = [_google_usuario(cfg, u, carpeta, estado) for u in usuarios]
    return {"servicio": "google", "usuarios": len(usuarios), "detalle": detalle}


# ------------------------------------------------------------------------------------------------ almacén (restic)
def _restic_env(env: dict) -> tuple[str, dict] | tuple[None, None]:
    import mantenimiento as _m
    repo, pwd = _m.repo_local(env)
    if not repo:
        return None, None
    return _m.restic_bin(), _m.restic_env(repo, pwd)


def _dir_nube() -> Path:
    base = os.environ.get("OCTOPUS_DATA") or "/data"
    return Path(base) / "nube"


def copiar(env: dict, config: dict, solo: str | None = None) -> dict:
    """Copia los servicios de nube configurados. config = {microsoft:{...}, google:{...}}. Guarda en el almacén."""
    binary, renv = _restic_env(env)
    if not binary:
        return {"status": "error", "message": "No se encuentra el almacén del servidor"}
    raiz = _dir_nube()
    raiz.mkdir(parents=True, exist_ok=True)
    estado_f = raiz / "estado.json"
    try:
        estado = json.loads(estado_f.read_text())
    except (OSError, ValueError):
        estado = {}
    pasos, detalle, errores = [], [], []
    for serv, fn in (("microsoft", _ms_copiar), ("google", _google_copiar)):
        if (solo and solo != serv) or not config.get(serv):
            continue
        carpeta = raiz / serv
        est = estado.setdefault(serv, {})
        try:
            pasos.append(f"{SERVICIOS[serv]}: copiando")
            r = fn(config[serv], carpeta, est)
            detalle.append(r)
            pasos.append(f"{SERVICIOS[serv]}: {r['usuarios']} usuario(s), "
                         f"{sum(d['nuevos'] for d in r['detalle'])} elemento(s) nuevos")
        except Exception as exc:
            errores.append(f"{SERVICIOS[serv]}: {exc}")
            pasos.append(f"{SERVICIOS[serv]}: ERROR {exc}")
    estado_f.write_text(json.dumps(estado))
    if not detalle and not errores:
        return {"status": "error", "message": "No hay ningún servicio de nube configurado", "pasos": pasos}
    cmd = [binary, "backup", str(raiz), "--tag", "octopus-nube", "--tag", "nube", "--host", "octopus-nube",
           "--exclude", str(estado_f), "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=renv, timeout=24 * 3600)
    if r.returncode not in (0, 3):
        return {"status": "error", "message": (r.stderr or r.stdout or "")[-500:], "detalle": detalle, "pasos": pasos}
    snap = ""
    for linea in (r.stdout or "").splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if d.get("message_type") == "summary":
            snap = d.get("snapshot_id", "")
    (raiz / "ultima.txt").write_text(datetime.now(timezone.utc).isoformat())
    res = {"status": "success" if not errores else "parcial", "snapshot_id": snap, "detalle": detalle, "pasos": pasos}
    if errores:
        res["aviso"] = "; ".join(errores)
    return res


def copias(env: dict) -> list[dict]:
    binary, renv = _restic_env(env)
    if not binary:
        return []
    r = subprocess.run([binary, "snapshots", "--json", "--host", "octopus-nube", "--tag", "nube"],
                       capture_output=True, text=True, env=renv, timeout=300)
    try:
        snaps = json.loads(r.stdout or "[]") or []
    except ValueError:
        snaps = []
    out = [{"id": s.get("short_id") or s.get("id", "")[:8], "time": s.get("time")} for s in snaps]
    out.sort(key=lambda c: c.get("time") or "", reverse=True)
    return out


def restaurar(env: dict, snapshot: str, destino: str | None = None) -> dict:
    """Recupera una copia de la nube en una carpeta del servidor (los .eml y los archivos, para abrir o volver a subir)."""
    if not re.fullmatch(r"[0-9a-fA-F]{6,64}", str(snapshot or "")):
        return {"status": "error", "message": "Copia no válida"}
    binary, renv = _restic_env(env)
    if not binary:
        return {"status": "error", "message": "No se encuentra el almacén del servidor"}
    base = destino or os.path.join(os.environ.get("OCTOPUS_DATA", "/data"), "nube-restaurada",
                                   datetime.now().strftime("%Y%m%d-%H%M"))
    Path(base).mkdir(parents=True, exist_ok=True)
    r = subprocess.run([binary, "restore", snapshot, "--target", base], capture_output=True, text=True,
                       env=renv, timeout=24 * 3600)
    if r.returncode != 0:
        return {"status": "error", "message": (r.stderr or r.stdout).strip()[-500:]}
    n = sum(1 for _ in Path(base).rglob("*") if _.is_file())
    return {"status": "success", "carpeta": base, "archivos": n,
            "instrucciones": "Los correos son archivos .eml (los abre Outlook, Thunderbird o se vuelven a importar); "
                             "los archivos de OneDrive/Drive se pueden volver a subir tal cual."}
