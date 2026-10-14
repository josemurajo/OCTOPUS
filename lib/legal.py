# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Textos legales del panel («Legal y privacidad»): licencia, componentes, privacidad y plantillas para la empresa.

Los textos están en archivos Markdown del proyecto (se pueden leer también sin el panel) y aquí se convierten en HTML
con un conversor mínimo (solo lo que usan esos archivos: títulos, párrafos, listas, tablas, citas, negrita, código y
enlaces). Todo el texto se escapa antes: un archivo no puede meter HTML en el panel.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Marca de autoría (texto en base64: cualquiera puede leerla con `base64 -d` o pidiéndoselo a una IA). No es un secreto:
# sirve para que la autoría viaje dentro del código aunque se copie un archivo suelto.
AUTORIA_B64 = (
    "T0NUT1BVUyBaZXJvLVRvdWNoIC0gY3JlYWRvIHBvciBKb3PDqSBNdXJpbGxvIFJham8gKGh0dHBzOi8vZ2l0aHViLmNvbS9q"
    "b3NlbXVyYWpvL09DVE9QVVMpLCAyMDI2LiBTb2Z0d2FyZSBsaWJyZSBBR1BMLTMuMC1vci1sYXRlcjogZXN0YSBhdHJpYnVj"
    "acOzbiBkZWJlIGNvbnNlcnZhcnNlIChMSUNFTlNFLCBzZWNjacOzbiA3LmI7IHZlciBOT1RJQ0UpLg=="
)


def autoria() -> str:
    """La frase de autoría, ya legible."""
    import base64
    try:
        return base64.b64decode(AUTORIA_B64).decode("utf-8")
    except Exception:
        return "OCTOPUS Zero-Touch - creado por José Murillo Rajo"


AUTOR = "José Murillo Rajo"

# clave -> (archivo, título, para quién)
DOCUMENTOS = {
    "licencia": ("LICENSE", "Licencia (GNU AGPL-3.0)", "todos"),
    "autoria": ("NOTICE", "Autoría y términos adicionales", "todos"),
    "terceros": ("TERCEROS.md", "Componentes de terceros", "todos"),
    "privacidad": ("legal/PRIVACIDAD_BORRADOR.md", "Protección de datos", "todos"),
    "seguridad": ("SECURITY.md", "Avisar de un fallo de seguridad", "todos"),
    "marca": ("MARCA.md", "El nombre y el logotipo", "todos"),
    "empresa": ("legal/LEEME.md", "Qué tiene que hacer la empresa que lo instala", "empresa"),
    "trabajadores": ("legal/NOTA_TRABAJADORES.md", "Nota informativa para los trabajadores", "empresa"),
    "registro": ("legal/REGISTRO_TRATAMIENTOS.md", "Registro de actividades de tratamiento", "empresa"),
    "evaluacion": ("legal/EVALUACION_IMPACTO_MONITORIZACION.md", "Evaluación de impacto de la monitorización", "empresa"),
}


def texto(clave: str, valores: dict | None = None) -> str | None:
    """El texto del documento, con los datos de esta instalación ({empresa}, {procesos}...) ya puestos."""
    d = DOCUMENTOS.get(clave)
    if not d:
        return None
    p = RAIZ / d[0]
    try:
        t = p.read_text(encoding="utf-8")
    except OSError:
        return None
    for k, v in (valores or {}).items():
        t = t.replace("{" + k + "}", str(v))
    return t


def _en_linea(s: str) -> str:
    s = html.escape(s, quote=True)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", s)

    def enlace(m):
        url = html.unescape(m.group(2))
        if url.startswith(("http://", "https://", "/", "#")):
            dest = url
        elif url.endswith(".md") or url in ("LICENSE", "legal/"):
            nombre = url.split("/")[-1] or "legal"
            clave = {"LICENSE": "licencia", "TERCEROS.md": "terceros", "SECURITY.md": "seguridad", "MARCA.md": "marca",
                     "PRIVACIDAD_BORRADOR.md": "privacidad", "LEEME.md": "empresa", "NOTA_TRABAJADORES.md": "trabajadores",
                     "REGISTRO_TRATAMIENTOS.md": "registro", "EVALUACION_IMPACTO_MONITORIZACION.md": "evaluacion"}.get(nombre)
            dest = f"/legal/{clave}" if clave else "/legal"
        else:
            return m.group(1)
        externo = ' target="_blank" rel="noopener noreferrer"' if dest.startswith("http") else ""
        return f'<a href="{html.escape(dest, quote=True)}"{externo}>{m.group(1)}</a>'
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", enlace, s)
    s = re.sub(r"(?<![\"=>])(https?://[^\s<)]+)", r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', s)
    return s


def a_html(md: str) -> str:
    """Markdown sencillo -> HTML seguro."""
    out, parrafo, lista, tabla, cita, codigo = [], [], None, [], [], None

    def cerrar():
        nonlocal parrafo, lista, tabla, cita
        if parrafo:
            out.append("<p>" + _en_linea(" ".join(parrafo)) + "</p>"); parrafo = []
        if lista:
            tipo, items = lista
            out.append(f"<{tipo}>" + "".join(f"<li>{_en_linea(i)}</li>" for i in items) + f"</{tipo}>"); lista = None
        if tabla:
            filas = [[c.strip() for c in f.strip().strip("|").split("|")] for f in tabla
                     if not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", f)]
            if filas:
                cab, *resto = filas
                out.append('<div class="tabla-legal"><table><thead><tr>' + "".join(f"<th>{_en_linea(c)}</th>" for c in cab)
                           + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{_en_linea(c)}</td>" for c in f) + "</tr>"
                                                              for f in resto) + "</tbody></table></div>")
            tabla = []
        if cita:
            out.append('<blockquote>' + _en_linea(" ".join(cita)) + "</blockquote>"); cita = []

    for linea in md.splitlines():
        if codigo is not None:
            if linea.strip().startswith("```"):
                out.append("<pre>" + html.escape("\n".join(codigo)) + "</pre>"); codigo = None
            else:
                codigo.append(linea)
            continue
        if linea.strip().startswith("```"):
            cerrar(); codigo = []; continue
        if not linea.strip():
            cerrar(); continue
        m = re.match(r"^(#{1,4})\s+(.*)", linea)
        if m:
            cerrar(); n = min(len(m.group(1)) + 1, 4)
            out.append(f"<h{n}>{_en_linea(m.group(2))}</h{n}>"); continue
        if linea.lstrip().startswith("|"):
            if parrafo or lista or cita:
                cerrar()
            tabla.append(linea); continue
        if linea.startswith(">"):
            if parrafo or lista or tabla:
                cerrar()
            cita.append(linea.lstrip("> ").strip()); continue
        m = re.match(r"^\s*([-*]|\d+\.)\s+(.*)", linea)
        if m:
            tipo = "ol" if m.group(1)[0].isdigit() else "ul"
            if parrafo or tabla or cita or (lista and lista[0] != tipo):
                cerrar()
            if not lista:
                lista = (tipo, [])
            lista[1].append(m.group(2)); continue
        if lista and linea.startswith("  "):      # continuación del punto anterior
            lista[1][-1] += " " + linea.strip(); continue
        if tabla or cita:
            cerrar()
        parrafo.append(linea.strip())
    if codigo is not None:
        out.append("<pre>" + html.escape("\n".join(codigo)) + "</pre>")
    cerrar()
    return "\n".join(out)
