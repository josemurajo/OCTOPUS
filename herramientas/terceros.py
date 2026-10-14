#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Lista de componentes de terceros y sus licencias (TERCEROS.md).

    python herramientas/terceros.py            escribe TERCEROS.md (con las dependencias de Python instaladas)
    python herramientas/terceros.py --revisar  solo comprueba: falla si alguna licencia es desconocida o
                                               incompatible con la AGPL-3.0 (lo usa GitHub en cada cambio)
"""
import re
import sys
from importlib import metadata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Programas que no son de Python: los descargan los instaladores en el equipo del cliente desde su web oficial
# (OCTOPUS no los reparte dentro de su código).
EXTERNOS = [
    ("restic", "BSD-2-Clause", "https://github.com/restic/restic", "Las copias (en el servidor y en cada equipo)"),
    ("rest-server", "BSD-2-Clause", "https://github.com/restic/rest-server", "El almacén de copias del servidor"),
    ("Python", "PSF-2.0", "https://www.python.org", "Ejecuta el servidor y el agente"),
    ("Docker CLI", "Apache-2.0", "https://github.com/docker/cli", "Sala de análisis (solo en el servidor Docker)"),
    ("ansible-core", "GPL-3.0-or-later", "https://github.com/ansible/ansible",
     "Despliegue a muchos equipos Linux; se ejecuta como programa aparte (no se mezcla con el código de OCTOPUS)"),
    ("smartmontools", "GPL-2.0-or-later", "https://www.smartmontools.org",
     "Salud del disco en la monitorización; se instala con el gestor de paquetes del sistema"),
    ("YARA", "BSD-3-Clause", "https://github.com/VirusTotal/yara", "Análisis de archivos sospechosos (servidor Docker)"),
    ("OpenSSL", "Apache-2.0", "https://www.openssl.org", "Certificados del servidor"),
]
# Dependencias de Python que solo se instalan en otro sistema (aquí no se pueden leer)
OTRO_SISTEMA = {"cheroot": ("BSD-3-Clause", "https://github.com/cherrypy/cheroot", "Servidor web del panel en Windows")}

# Licencias que se pueden combinar con la AGPL-3.0 (las de la lista, o una expresión hecha solo con ellas)
COMPATIBLES = {"MIT", "BSD", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "Apache", "ISC", "PSF-2.0", "Python-2.0",
               "LGPL-2.1", "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0", "LGPL-3.0-only", "LGPL-3.0-or-later",
               "GPL-3.0", "GPL-3.0-or-later", "GPL-2.0-or-later", "AGPL-3.0", "AGPL-3.0-or-later", "MPL-2.0",
               "Unlicense", "0BSD", "MIT-0", "Zlib", "CC0-1.0", "HPND", "MIT-CMU"}
_CLASIF = {"MIT License": "MIT", "BSD License": "BSD", "Apache Software License": "Apache-2.0",
           "ISC License (ISCL)": "ISC", "Python Software Foundation License": "PSF-2.0",
           "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.1-or-later",
           "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0", "GNU Library or Lesser General Public License (LGPL)": "LGPL-2.1",
           "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
           "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "The Unlicense (Unlicense)": "Unlicense",
           "Historical Permission Notice and Disclaimer (HPND)": "HPND"}
_TEXTO = [(r"\bMIT\b", "MIT"), (r"BSD.*3|3-Clause|New BSD|Modified BSD", "BSD-3-Clause"), (r"BSD.*2|2-Clause|Simplified", "BSD-2-Clause"),
          (r"\bBSD\b", "BSD"), (r"Apache", "Apache-2.0"), (r"LGPL.*3|Lesser.*3", "LGPL-3.0"), (r"LGPL|Lesser", "LGPL-2.1"),
          (r"\bISC\b", "ISC"), (r"MPL|Mozilla", "MPL-2.0"), (r"PSF|Python Software", "PSF-2.0")]


def _nombre(req: str) -> str:
    return re.split(r"[\s;<>=!~\[]", req.strip(), maxsplit=1)[0].lower().replace("_", "-")


def licencia(dist) -> str:
    m = dist.metadata
    expr = (m.get("License-Expression") or "").strip()
    if expr:
        return expr
    clas = [c.split(" :: ")[-1] for c in (m.get_all("Classifier") or []) if c.startswith("License :: OSI Approved")]
    if clas:
        return " OR ".join(sorted({_CLASIF.get(c, c) for c in clas}))
    texto = (m.get("License") or "").strip()
    for patron, spdx in _TEXTO:
        if texto and len(texto) < 4000 and re.search(patron, texto, re.I):
            return spdx
    return texto[:60] or "desconocida"


def compatible(lic: str) -> bool:
    partes = [p.strip("() ") for p in re.split(r"\bOR\b|\bAND\b|\bWITH\b|/|,", lic) if p.strip("() ")]
    if not partes:
        return False
    if " AND " in lic:      # todas tienen que valer
        return all(p in COMPATIBLES or p.startswith("LLVM-exception") for p in partes)
    return any(p in COMPATIBLES for p in partes)      # con OR (o una sola) basta una


def dependencias():
    """Las de requirements.txt y las que estas arrastran, tal como estan instaladas."""
    pendientes = [_nombre(l) for l in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.lstrip().startswith("#")]
    vistas, falta = {}, []
    while pendientes:
        n = pendientes.pop()
        if n in vistas or n in falta:
            continue
        try:
            d = metadata.distribution(n)
        except metadata.PackageNotFoundError:
            falta.append(n)
            continue
        vistas[n] = d
        for r in d.requires or []:
            if "extra ==" in r:
                continue
            try:
                from packaging.requirements import Requirement
                rq = Requirement(r)
                if rq.marker and not rq.marker.evaluate():
                    continue
                pendientes.append(rq.name.lower().replace("_", "-"))
            except Exception:
                pendientes.append(_nombre(r))
    return vistas, falta


def main(argv):
    vistas, falta = dependencias()
    filas, malas = [], []
    for n, d in sorted(vistas.items()):
        lic = licencia(d)
        urls = {u.split(",", 1)[0].strip().lower(): u.split(",", 1)[-1].strip() for u in (d.metadata.get_all("Project-URL") or [])}
        url = d.metadata.get("Home-page") or next((urls[k] for k in ("source", "source code", "repository", "homepage", "home",
                                                                     "documentation") if k in urls), next(iter(urls.values()), ""))
        filas.append((d.metadata["Name"], d.version, lic, url))
        if not compatible(lic):
            malas.append(f"{d.metadata['Name']} {d.version}: {lic}")
    for n in falta:
        if n not in OTRO_SISTEMA:
            malas.append(f"{n}: no está instalado, no se puede comprobar su licencia")
    if "--revisar" in argv:
        print(f"{len(filas)} componentes de Python revisados")
        for m in malas:
            print("REVISAR:", m)
        return 1 if malas else 0
    out = ["# Componentes de terceros", "",
           "OCTOPUS Zero-Touch (AGPL-3.0-or-later) usa estos componentes de otros proyectos, cada uno con su licencia.",
           "Todas permiten usarlos junto a la AGPL-3.0. Los textos completos de cada licencia vienen con cada componente",
           "(carpeta del paquete instalado, o la web del proyecto). Esta lista la genera `python herramientas/terceros.py`.", "",
           "## Programas que se descargan al instalar", "", "| Componente | Licencia | Web | Para qué |", "|---|---|---|---|"]
    out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in EXTERNOS]
    out += ["", "## Bibliotecas de Python (`requirements.txt` y lo que necesitan)", "",
            "| Componente | Versión revisada | Licencia | Web |", "|---|---|---|---|"]
    out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in filas]
    for n, (lic, url, para) in OTRO_SISTEMA.items():
        if n not in vistas:
            out.append(f"| {n} | (solo {para.split(' en ')[-1]}) | {lic} | {url} |")
    if malas:
        out += ["", "## Pendiente de revisar", ""] + [f"- {m}" for m in malas]
    (RAIZ / "TERCEROS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"TERCEROS.md: {len(EXTERNOS)} programas y {len(filas)} bibliotecas" + (f"; {len(malas)} por revisar" if malas else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
