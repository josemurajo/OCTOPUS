"""Prueba del MODO CASA.

    python tests/ci/prueba_casa.py            el panel con una base de datos nueva (cualquier sistema): «¿casa o
                                              empresa?», ajustes de cada modo, menú, mover las copias de disco...
    python tests/ci/prueba_casa.py nativo     contra el servidor NATIVO ya instalado en Windows o Mac (pruebas de
                                              GitHub y el Espacio aislado de Windows): elegir casa, «Proteger este
                                              ordenador» de verdad, copia, y pasar las copias a otro disco (si lo
                                              hay) y seguir copiando allí sin perder nada.
                                              (en Mac, como root: sudo <python del servidor> ...)
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FALLOS = []


def chk(c, n, x=""):
    print("PASS" if c else "FAIL", n, str(x)[:300])
    if not c:
        FALLOS.append(n)


def tok(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


# =============================================================================================== 1. panel (unidad)
def unidad():
    tmp = tempfile.mkdtemp()
    os.environ.update(DB_PATH=os.path.join(tmp, "nueva.db"), OCTOPUS_DATA=os.path.join(tmp, "data"),
                      ADMIN_PASSWORD="ClaveInicialDePrueba-123", PANEL_HTTPS="0",
                      OCTOPUS_BOVEDA_DIR=os.path.join(tmp, "boveda"))
    sys.path.insert(0, str(RAIZ / "lib"))
    import admin_panel as a
    import casa
    a.app.config.update(TESTING=True)
    c = a.app.test_client()

    def post(ruta, datos, desde):
        return c.post(ruta, data=dict(datos, csrf_token=tok(c.get(desde).get_data(as_text=True))))

    r = c.post("/login", data={"csrf_token": tok(c.get("/login").get_data(as_text=True)), "username": "admin",
                               "password": "ClaveInicialDePrueba-123"})
    nueva = "OtraClaveSegura-2026!"
    r = post("/cuenta/contrasena", {"actual": "ClaveInicialDePrueba-123", "nueva": nueva, "repetir": nueva},
             "/cuenta/contrasena")
    r = c.get("/inicio")
    chk(r.status_code == 302 and r.headers["Location"].endswith("/bienvenida"),
        "tras cambiar la contraseña, pregunta «¿casa o empresa?»", r.headers.get("Location"))
    t = c.get("/bienvenida").get_data(as_text=True)
    chk("Para casa" in t and "Para una empresa" in t and "máquina aparte" in t, "explica las dos opciones")
    chk(c.get("/ajustes").status_code == 302, "no deja usar el panel hasta elegir")

    r = post("/bienvenida", {"modo": "casa"}, "/bienvenida")
    chk(r.status_code == 302 and r.headers["Location"].endswith("/casa"), "elegir casa lleva a «Tu ordenador»")
    cm = a.config_manager
    chk(cm.get_config("modo_uso") == "casa", "queda guardado el modo casa")
    chk(cm.get_config("dosfa") is False and cm.get_config("informe_mensual") is False and
        cm.get_config("discreto") is True, "ajustes de casa: sin 2FA obligatoria ni informes, discreto encendido")
    t = c.get("/inicio").get_data(as_text=True)
    chk(c.get("/inicio").status_code == 200, "en casa no exige activar el móvil")
    chk("Tu ordenador" in t and "Ordenadores" in t and ">Incidentes" not in t, "menú de casa, más sencillo")
    chk("Proteger este ordenador" in t, "Inicio invita a proteger este ordenador")
    t = c.get("/casa").get_data(as_text=True)
    chk(c.get("/casa").status_code == 200 and "¿Dónde guardo las copias?" in t or "Docker" in t,
        "la pantalla «Tu ordenador» se abre", t[:200])

    # con este ordenador ya protegido, la pantalla sigue abriéndose
    with a.get_db_connection() as cx:
        cx.execute("INSERT INTO systems (hostname, ip_address, os_family, status, notes) VALUES (?, '127.0.0.1', "
                   "'windows', 'unknown', ?)", (casa.nombre_este_equipo(), json.dumps({"rutas": ["C:/x"]})))
    r = c.get("/casa")
    chk(r.status_code == 200, "«Tu ordenador» con el ordenador ya protegido", r.status_code)
    with a.get_db_connection() as cx:
        cx.execute("DELETE FROM systems")

    # carpetas personales (con una carpeta de usuarios de mentira)
    usuarios = Path(tmp) / "Users"
    for p in ("ana/Documents", "ana/Pictures", "ana/OneDrive/Documentos", "Public/Documents", "Default/Documents"):
        (usuarios / p).mkdir(parents=True)
    casa.SISTEMA = "windows"
    encontradas = casa.carpetas_personales(str(usuarios))
    casa.SISTEMA = __import__("platform").system().lower()
    chk(any(x.endswith("Documents") and "ana" in x for x in encontradas) and
        not any("Public" in x or "Default" in x for x in encontradas) and
        any("OneDrive" in x for x in encontradas), "carpetas personales: las de cada persona, no las del sistema",
        encontradas)

    # mover las copias a otro disco: se copia todo, se apunta, se reinicia el almacén y no se borra lo viejo
    viejo = Path(os.environ["OCTOPUS_BOVEDA_DIR"]) / "octopus-backups"
    (viejo / "data").mkdir(parents=True)
    (viejo / "config").write_text("repo", encoding="utf-8")
    (viejo / "data" / "pack1").write_bytes(b"x" * 1000)
    otro = Path(tmp) / "USB"
    otro.mkdir()
    env = Path(tmp) / ".env"
    env.write_text("OCTOPUS_IP=1.2.3.4\nOCTOPUS_BOVEDA_DIR=/viejo\n", encoding="utf-8")
    casa.mover_copias(str(otro), env)
    for _ in range(50):
        if (casa.estado().get("mover") or {}).get("fase") in ("hecho", "error"):
            break
        time.sleep(0.1)
    e = casa.estado().get("mover") or {}
    nuevo = otro / "OCTOPUS-copias" / "octopus-backups"
    chk(e.get("fase") == "hecho" and (nuevo / "data" / "pack1").is_file(), "pasa las copias al otro disco", e)
    chk((viejo / "data" / "pack1").is_file(), "no borra las copias viejas")
    chk(str(casa.boveda_actual()) == str(otro / "OCTOPUS-copias"), "el almacén apunta al disco nuevo")
    chk(f"OCTOPUS_BOVEDA_DIR={otro / 'OCTOPUS-copias'}" in env.read_text(encoding="utf-8") and
        "OCTOPUS_IP=1.2.3.4" in env.read_text(encoding="utf-8"), "se apunta también en los ajustes del servidor")
    chk((casa.DATA / "reiniciar_servicios").is_file(), "pide reiniciar el almacén para usar el disco nuevo")

    # disco desconectado: el servidor lo nota y el panel lo dice claro
    sys.path.insert(0, str(RAIZ / "lib"))
    import servidor
    servidor.DATA, servidor.RUTA_ELEGIDA = casa.DATA, casa.DATA / "boveda_ruta.txt"
    servidor.DESCONECTADA = casa.DATA / "boveda_desconectada"
    servidor.RUTA_ELEGIDA.write_text(str(Path(tmp) / "no_existe" / "x" / "OCTOPUS-copias"), encoding="utf-8")
    servidor.boveda_actual()
    chk(servidor.DESCONECTADA.is_file(), "si el disco no está conectado, se apunta")
    chk("Conecta el disco de las copias" in c.get("/inicio").get_data(as_text=True), "Inicio avisa: conecta el disco")
    servidor.RUTA_ELEGIDA.write_text(str(otro / "OCTOPUS-copias"), encoding="utf-8")
    servidor.boveda_actual()
    chk(not servidor.DESCONECTADA.is_file(), "al conectarlo, el aviso se va solo")

    # cambiar a empresa desde Ajustes
    r = post("/ajustes/modo", {"modo": "empresa"}, "/ajustes")
    chk(cm.get_config("modo_uso") == "empresa" and cm.get_config("dosfa") is True, "cambiar a empresa: vuelve la 2FA")
    r = c.get("/acceso-directo/windows")
    chk(r.status_code == 200 and b"[InternetShortcut]" in r.data and b"URL=http" in r.data,
        "empresa: icono de OCTOPUS para el escritorio del PC del jefe (Windows)", r.data[:80])
    r = c.get("/acceso-directo/mac")
    chk(r.status_code == 200 and b"<plist" in r.data, "y para Mac")


# =============================================================================================== 2. Windows de verdad
CLAVE_CASA = "ClaveDeCasa-2026!x"   # solo en máquinas de prueba (GitHub y el Espacio aislado, que se borran)


def nativo():
    import platform
    import requests
    import urllib3
    urllib3.disable_warnings()
    windows = platform.system() == "Windows"
    R = Path(os.environ.get("OCTOPUS_RAIZ", r"C:\ProgramData\OCTOPUS-Servidor" if windows else "/usr/local/octopus-servidor"))
    B = "https://127.0.0.1:8080"
    s = requests.Session()
    s.verify = False
    s.trust_env = False

    def get(p):
        return s.get(B + p, timeout=60)

    def post(p, datos, desde):
        return s.post(B + p, data=dict(datos, csrf_token=tok(get(desde).text)), timeout=60)

    cred = (R / "data" / "CREDENCIALES_INICIALES.txt").read_text(encoding="utf-8")
    inicial = re.search(r"Contrasen?ñ?a[^:]*:\s*(\S+)", cred).group(1)
    s.post(B + "/login", data={"csrf_token": tok(get("/login").text), "username": "admin", "password": inicial})
    nueva = CLAVE_CASA
    post("/cuenta/contrasena", {"actual": inicial, "nueva": nueva, "repetir": nueva}, "/cuenta/contrasena")
    chk(get("/inicio").url.endswith("/bienvenida"), "primera vez: pregunta casa o empresa")
    r = post("/bienvenida", {"modo": "casa"}, "/bienvenida")
    chk(r.url.endswith("/casa") and "Proteger este ordenador" in r.text, "modo casa: pantalla «Tu ordenador»")

    # una carpeta personal de mentira para tener algo que copiar
    perfil = (Path(os.environ.get("SystemDrive", "C:") + "\\Users") if windows else Path("/Users")) / "prueba_casa" / "Documents"
    perfil.mkdir(parents=True, exist_ok=True)
    (perfil / "foto_de_las_vacaciones.txt").write_text("recuerdo importante", encoding="utf-8")
    t = get("/casa").text
    chk(str(perfil) in t, "encuentra las carpetas personales de este ordenador", str(perfil))
    r = post("/casa/proteger", {"carpetas": str(perfil)}, "/casa")
    fase = ""
    for _ in range(120):
        fase = (get("/casa/estado").json().get("proteger") or {}).get("fase")
        if fase in ("hecho", "error"):
            break
        time.sleep(5)
    chk(fase == "hecho", "«Proteger este ordenador» instala el agente aquí mismo", get("/casa/estado").json())
    log = R / "datos" / "logs" / "casa_instalacion.log"
    if fase != "hecho" and log.is_file():
        print(log.read_text(encoding="utf-8", errors="replace")[-3000:])

    sys.path.insert(0, str(R / "lib"))
    os.chdir(R)
    for linea in (R / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.startswith("#"):
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    import ordenes
    ordenes.init(str(R / "data" / "admin_panel.db"))
    equipo = (get("/casa/estado").json().get("proteger") or {}).get("equipo", "")   # el nombre con el que se dio de alta

    def pedir(metodo, ruta, datos=None, seg=600):
        return ordenes.pedir(equipo, metodo, ruta, datos, seg)

    for _ in range(90):
        if ordenes.en_linea(equipo):
            break
        time.sleep(2)
    chk(ordenes.en_linea(equipo), "el agente de este ordenador se conecta", equipo)
    r1 = pedir("POST", "/webhook/backup", {}, 1200)
    chk(r1.get("status") == "success", "primera copia en modo casa (vigilada por el modo discreto)", r1)
    chk("discreto" in r1, "la copia dice si fue despacio para no molestar", r1.get("discreto"))
    if windows:
        import subprocess
        estado = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Octopus-estado" / "estado.json"
        e = json.loads(estado.read_text(encoding="utf-8")) if estado.is_file() else {}
        chk(e.get("ok") is True and e.get("ultima_copia"), "deja el estado para el icono junto al reloj (sin claves)", e)
        tarea = subprocess.run(["schtasks", "/Query", "/TN", "OCTOPUS Icono"], capture_output=True, text=True)
        chk(tarea.returncode == 0, "en casa se instala el icono «OCTOPUS te protege» (al iniciar sesión)")
        icono = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Octopus" / "octopus_bandeja.ps1"
        t = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(icono), "-Prueba"],
                           capture_output=True, text=True, timeout=60).stdout.strip()
        chk(t.startswith("OK|OCTOPUS te protege. Ultima copia hace"), "el icono dice «te protege» y cuándo fue la copia", t)

    # pasar las copias a otro disco (en GitHub Windows es D:; en Mac, un disco de mentira montado en /Volumes)
    discos = get("/casa/discos").json()
    chk(any(d["sistema"] for d in discos), "lista los discos y sabe cuál es el del sistema", discos)
    preferido = os.environ.get("OCTOPUS_PRUEBA_DISCO", "")
    otro = next((d for d in discos if preferido and d["ruta"].rstrip("/\\") == preferido.rstrip("/\\")), None) \
        or next((d for d in discos if not d["sistema"]), None)
    if not otro:
        print("(este ordenador no tiene otro disco: no se prueba pasar las copias)")
        return
    r = post("/casa/disco", {"disco": otro["ruta"]}, "/casa")
    fase = ""
    for _ in range(60):
        try:
            fase = (get("/casa/estado").json().get("mover") or {}).get("fase")
        except Exception:
            fase = ""   # el panel se está reiniciando
        if fase in ("hecho", "error"):
            break
        time.sleep(3)
    chk(fase == "hecho" and (Path(otro["ruta"]) / "OCTOPUS-copias" / "octopus-backups" / "config").is_file(),
        f"las copias pasan al otro disco ({otro['ruta']})", fase)
    for _ in range(60):   # el almacén se reinicia apuntando al disco nuevo
        try:
            if get("/healthz").status_code == 200:
                break
        except Exception:
            pass
        time.sleep(3)
    time.sleep(10)
    r2 = pedir("POST", "/webhook/backup", {}, 1200)
    chk(r2.get("status") == "success", "después de cambiar de disco, las copias siguen", r2)
    snaps = pedir("GET", "/snapshots", seg=120)
    chk(snaps.get("count", 0) >= 2, "en el disco nuevo están las copias de antes y la nueva", snaps.get("count"))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("nativo", "windows"):
        nativo()
    else:
        unidad()
    print("FALLOS:", FALLOS or "ninguno")
    sys.exit(1 if FALLOS else 0)
