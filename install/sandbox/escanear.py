#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Analisis estatico de las muestras: hash, tipo real, entropia y senales de sospecha. Salida JSON."""
import hashlib, json, math, os, subprocess, sys

RANSOM_EXT = {".locked", ".encrypted", ".enc", ".crypt", ".crypted", ".crypto", ".lockbit", ".ryk", ".wncry",
              ".wnry", ".cerber", ".locky", ".djvu", ".conti", ".phobos", ".makop", ".ransom", ".akira", ".royal"}
NOTE_WORDS = ("decrypt", "ransom", "recover", "readme", "restore_files", "how_to")
SCRIPT_EXT = {".ps1", ".vbs", ".js", ".jse", ".bat", ".cmd", ".hta", ".sh", ".py", ".scr", ".lnk", ".wsf", ".jar"}
EXEC_EXT = {".exe", ".dll", ".sys", ".com", ".msi", ".so", ".elf", ".bin"}


def entropia(data):
    if not data:
        return 0.0
    c = [0] * 256
    for b in data:
        c[b] += 1
    n = len(data)
    return -sum(x / n * math.log2(x / n) for x in c if x)


def tipo(path):
    try:
        return subprocess.run(["file", "-b", path], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def main(base):
    out = []
    for root, _, files in os.walk(base):
        for f in files:
            p = os.path.join(root, f)
            try:
                data = open(p, "rb").read()
            except OSError:
                continue
            nombre = f.lower()
            ext = os.path.splitext(nombre)[1]
            t = tipo(p)
            ent = round(entropia(data[:65536]), 2)
            motivos = []
            if ext in RANSOM_EXT:
                motivos.append("extensión típica de ransomware")
            if any(w in nombre for w in NOTE_WORDS) and ext in (".txt", ".html", ".hta", ".url"):
                motivos.append("parece una nota de rescate")
            if data[:2] == b"MZ" or data[:4] == b"\x7fELF":
                motivos.append("programa ejecutable")
            elif ext in EXEC_EXT:
                motivos.append("extensión de ejecutable")
            if ext in SCRIPT_EXT:
                motivos.append("script")
            partes = nombre.split(".")
            if len(partes) > 2 and "." + partes[-1] in (EXEC_EXT | SCRIPT_EXT):
                motivos.append("doble extensión")
            comprimido = any(k in t.lower() for k in ("zip", "compressed", "jpeg", "png", "gzip", "7-zip", "pdf", "video", "audio"))
            if ent > 7.5 and not comprimido and len(data) > 256:
                motivos.append(f"contenido cifrado o empaquetado (entropía {ent})")
            out.append({"ruta": os.path.relpath(p, base), "tamano": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(), "tipo": t, "entropia": ent,
                        "motivos": motivos})
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/muestras")
