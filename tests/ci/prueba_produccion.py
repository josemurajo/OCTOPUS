"""Comprobaciones de «listo para producción» que no necesitan equipos: datos del autor, textos legales completos,
versión y CHANGELOG, nada de modo depuración, y el primer acceso de una instalación nueva (sin vueltas infinitas).

    python tests/ci/prueba_produccion.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "lib"))
FALLOS = []


def chk(cond, nombre, extra=""):
    print("PASS" if cond else "FAIL", nombre, extra)
    if not cond:
        FALLOS.append(nombre)


# ---------------------------------------------------------------- datos del autor
import legal  # noqa: E402

d = legal.datos_autor()
chk(d["NOMBRE"] == "José Murillo Rajo", "el nombre del autor sale de DATOS_DEL_AUTOR.txt")
original = legal.RAIZ
with tempfile.TemporaryDirectory() as t:
    legal.RAIZ = Path(t)
    chk(legal.datos_autor()["CORREO_PRIVACIDAD"] == "", "sin archivo: correos vacíos, sin fallar")
    (Path(t) / "DATOS_DEL_AUTOR.txt").write_text(
        "# comentario\nCORREO_PRIVACIDAD = privacidad@ejemplo.org \nCORREO_SEGURIDAD=esto no es un correo\n"
        "CONSERVAR_SUGERENCIAS=12 meses\nOTRA_COSA=x\n", encoding="utf-8")
    d2 = legal.datos_autor()
    chk(d2["CORREO_PRIVACIDAD"] == "privacidad@ejemplo.org", "lee un correo bien escrito (quita espacios)")
    chk(d2["CORREO_SEGURIDAD"] == "", "ignora algo que no es un correo")
    chk(d2["CONSERVAR_SUGERENCIAS"] == "12 meses" and "OTRA_COSA" not in d2, "lee el plazo e ignora claves desconocidas")
legal.RAIZ = original

for clave in ("privacidad", "seguridad"):
    t = legal.texto(clave) or ""
    restos = re.findall(r"\[(?:nombre de quien|correo|24 meses)[^\]]*\]", t)
    chk(t and not restos, f"«{clave}» sin huecos del autor por rellenar en el panel", restos)

ajeno = (RAIZ / "DATOS_DEL_AUTOR.txt").read_text(encoding="utf-8")
chk(not re.search(r"(?im)^\s*[A-Z_]*(PASS|CLAVE|TOKEN|SECRET)[A-Z_]*\s*=", ajeno),
    "DATOS_DEL_AUTOR.txt no tiene sitio para contraseñas ni claves (es público)")

# ---------------------------------------------------------------- versión
v = (RAIZ / "VERSION").read_text(encoding="utf-8").strip()
chk(re.fullmatch(r"\d+\.\d+\.\d+", v) is not None, "VERSION es un número de versión", v)
chk(re.search(rf"(?m)^## {re.escape(v)}\b", (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")) is not None,
    "CHANGELOG.md explica la versión actual", v)

# ---------------------------------------------------------------- nada de depuración
codigo = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (RAIZ / "lib").glob("*.py"))
chk(not re.search(r"debug\s*=\s*True", codigo), "ningún módulo arranca en modo depuración")

# ---------------------------------------------------------------- primer acceso de una instalación nueva
tmp = tempfile.mkdtemp()
os.environ.update(DB_PATH=os.path.join(tmp, "nueva.db"), OCTOPUS_DATA=os.path.join(tmp, "data"),
                  ADMIN_PASSWORD="ClaveInicialDePrueba-123", PANEL_HTTPS="0")
import admin_panel as a  # noqa: E402

a.app.config.update(TESTING=True)
c = a.app.test_client()
html = c.get("/login").get_data(as_text=True)
tok = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
r = c.post("/login", data={"csrf_token": tok, "username": "admin", "password": "ClaveInicialDePrueba-123"})
camino = []
for _ in range(8):   # seguir las redirecciones a mano: si da vueltas, se ve
    if r.status_code not in (301, 302, 303):
        break
    destino = r.headers["Location"].replace("http://localhost", "")
    camino.append(destino)
    r = c.get(destino)
chk(r.status_code == 200 and camino and camino[-1].endswith("/cuenta/contrasena"),
    "primer acceso: lleva a cambiar la contraseña, sin dar vueltas", " → ".join(camino))

print("FALLOS:", FALLOS or "ninguno")
sys.exit(1 if FALLOS else 0)
