# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - DESTINOS DE COPIA: que un equipo copie DIRECTAMENTE a otro sitio, con OCTOPUS mandando y vigilando.

Para servidores enormes (que no pasen terabytes por el servidor de OCTOPUS), sucursales con su propio NAS o una
segunda copia fuera de la oficina. Los datos van del equipo al destino; OCTOPUS solo da las órdenes, guarda la
lista de copias y avisa si algo falla. Cada equipo elige en su ficha («Dónde van sus copias»):

  octopus   al almacén del servidor OCTOPUS (lo normal; protegido contra borrado)
  carpeta   una carpeta del propio equipo, otro disco o una carpeta de red (D:\\Copias, \\\\NAS\\copias, /mnt/nas)
  s3        un almacenamiento S3 (MinIO, Wasabi, Backblaze B2, Synology C2, AWS...) con su clave
  rest      otro almacén de copias tipo rest-server (por ejemplo en un NAS): dirección, usuario y contraseña

y si va «en lugar de» la copia al servidor OCTOPUS o «además» (una segunda copia).

Las contraseñas del destino y la clave de cifrado de esas copias se guardan cifradas en la base de datos, y la clave
de cifrado va en el kit de recuperación: sin ella, esas copias no se pueden abrir si se pierde el servidor.
"""
from __future__ import annotations

import json
import secrets
from urllib.parse import quote, urlsplit, urlunsplit

TIPOS = {
    "octopus": "El servidor OCTOPUS (lo normal)",
    "carpeta": "Una carpeta, otro disco o una carpeta de red",
    "s3": "Almacenamiento S3 (MinIO, Wasabi, Backblaze B2...)",
    "rest": "Otro almacén de copias (rest-server, por ejemplo en un NAS)",
}
MODOS = {"en_lugar": "En lugar de la copia al servidor OCTOPUS", "ademas": "Además de la copia al servidor OCTOPUS"}
RETENCION = ["--keep-daily", "7", "--keep-weekly", "5", "--keep-monthly", "12"]


def _cifrar(db_file, datos: dict) -> str:
    import dosfa
    return dosfa.cifrar(db_file, json.dumps(datos))


def _descifrar(db_file, texto: str) -> dict:
    import dosfa
    try:
        return json.loads(dosfa.descifrar(db_file, texto))
    except Exception:
        return {}


def leer(notas: dict) -> dict:
    """Lo que se puede enseñar en el panel (sin contraseñas)."""
    d = notas.get("destino") or {}
    return {"tipo": d.get("tipo") or "octopus", "modo": d.get("modo") or "en_lugar", "donde": d.get("donde") or ""}


def activo(notas: dict) -> bool:
    return (notas.get("destino") or {}).get("tipo", "octopus") != "octopus"


def en_lugar(notas: dict) -> bool:
    return activo(notas) and (notas.get("destino") or {}).get("modo", "en_lugar") == "en_lugar"


def guardar(db_file, notas: dict, form: dict) -> tuple[dict, str | None]:
    """Valida lo que viene del formulario y devuelve (notas nuevas, error). No pierde la clave de cifrado de antes."""
    tipo = (form.get("tipo") or "octopus").strip()
    if tipo not in TIPOS:
        return notas, "Elige un destino de la lista."
    notas = dict(notas)
    if tipo == "octopus":
        viejo = notas.pop("destino", None)
        if viejo and viejo.get("secreto"):
            notas["destino_anterior"] = viejo     # por si se vuelve: la clave de esas copias no se pierde
        return notas, None
    modo = form.get("modo") if form.get("modo") in MODOS else "en_lugar"
    anterior = notas.get("destino") or notas.get("destino_anterior") or {}
    sec_ant = _descifrar(db_file, anterior.get("secreto", "")) if anterior.get("secreto") else {}
    sec = {"clave_repo": sec_ant.get("clave_repo") or secrets.token_urlsafe(32)}
    if tipo == "carpeta":
        ruta = (form.get("ruta") or "").strip()
        if len(ruta) < 2 or "\n" in ruta:
            return notas, "Escribe la carpeta (por ejemplo D:\\Copias o \\\\NAS\\copias)."
        donde, sec["repo"] = ruta, ruta
    elif tipo == "s3":
        ep, bucket = (form.get("endpoint") or "").strip().rstrip("/"), (form.get("bucket") or "").strip().strip("/")
        if not ep.startswith(("https://", "http://")) or not bucket:
            return notas, "Escribe la dirección del S3 (https://...) y el nombre del «bucket»."
        acceso, secreto = (form.get("acceso") or "").strip(), (form.get("secreto") or "").strip()
        if not acceso or not secreto:
            if sec_ant.get("env", {}).get("AWS_ACCESS_KEY_ID") and not acceso and not secreto:
                acceso, secreto = sec_ant["env"]["AWS_ACCESS_KEY_ID"], sec_ant["env"]["AWS_SECRET_ACCESS_KEY"]
            else:
                return notas, "Faltan la clave de acceso y la clave secreta del S3."
        donde = f"{ep}/{bucket}"
        sec["repo"] = f"s3:{ep}/{bucket}"
        sec["env"] = {"AWS_ACCESS_KEY_ID": acceso, "AWS_SECRET_ACCESS_KEY": secreto,
                      "AWS_DEFAULT_REGION": (form.get("region") or "").strip() or "us-east-1"}
    else:   # rest
        url = (form.get("url") or "").strip().rstrip("/")
        p = urlsplit(url)
        if p.scheme not in ("https", "http") or not p.hostname:
            return notas, "Escribe la dirección del almacén (https://nas:8000/copias)."
        usuario, clave = (form.get("usuario") or "").strip(), (form.get("clave") or "").strip()
        if not clave and sec_ant.get("rest_clave") and usuario == sec_ant.get("rest_usuario"):
            clave = sec_ant["rest_clave"]
        donde = urlunsplit((p.scheme, p.netloc.split("@")[-1], p.path, "", ""))
        netloc = p.netloc.split("@")[-1]
        if usuario:
            netloc = f"{quote(usuario, safe='')}:{quote(clave, safe='')}@{netloc}"
        sec["repo"] = "rest:" + urlunsplit((p.scheme, netloc, p.path, "", ""))
        sec["rest_usuario"], sec["rest_clave"] = usuario, clave
    notas["destino"] = {"tipo": tipo, "modo": modo, "donde": donde[:300], "secreto": _cifrar(db_file, sec)}
    notas.pop("destino_anterior", None)
    return notas, None


def para_agente(db_file, notas: dict) -> dict:
    """Lo que necesita el agente para copiar al destino (se manda en cada consulta, por HTTPS, al equipo dueño)."""
    if not activo(notas):
        return {}
    d = notas["destino"]
    sec = _descifrar(db_file, d.get("secreto", ""))
    if not sec.get("repo") or not sec.get("clave_repo"):
        return {}
    return {"tipo": d["tipo"], "modo": d.get("modo", "en_lugar"), "repo": sec["repo"], "password": sec["clave_repo"],
            "env": sec.get("env") or {}, "retencion": RETENCION}


def para_kit(db_file, equipos: list) -> str:
    """Las claves de las copias que van a otros destinos (sin ellas no se abren si se pierde el servidor)."""
    lineas = []
    for nombre, notas in equipos:
        for clave in ("destino", "destino_anterior"):
            d = notas.get(clave) or {}
            if d.get("secreto"):
                sec = _descifrar(db_file, d["secreto"])
                lineas.append(f"- {nombre}{' (destino anterior)' if clave != 'destino' else ''}: {TIPOS.get(d.get('tipo'), d.get('tipo'))}"
                              f" en {d.get('donde')}\n    RESTIC_REPOSITORY={sec.get('repo', '')}\n"
                              f"    RESTIC_PASSWORD={sec.get('clave_repo', '')}")
    if not lineas:
        return ""
    return ("\n\n=== COPIAS QUE VAN A OTROS DESTINOS (Destinos de copia) ===\n"
            "Se abren con restic poniendo estas dos líneas (y, en S3, la clave de acceso del S3):\n" + "\n".join(lineas) + "\n")


def lista_copias(texto_json) -> list:
    """Lista de copias que devuelve el agente (/snapshots) en el formato del panel."""
    from agentes import parse_time
    salida = []
    for s in texto_json or []:
        salida.append({"id": (s.get("id") or "")[:8], "time": parse_time(s.get("time")), "paths": s.get("paths") or [],
                       "tags": s.get("tags") or []})
    salida.sort(key=lambda c: c["time"].timestamp() if c["time"] else 0, reverse=True)
    return salida
