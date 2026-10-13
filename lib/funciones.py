#!/usr/bin/env python3
"""
OCTOPUS - Lista de todas las funciones que se pueden encender, apagar y ajustar (Ajustes -> Funciones).

Un solo sitio para todo lo configurable:
  - nivel "basico": lo que entiende cualquiera (se ve siempre).
  - nivel "experto": numeros finos y opciones avanzadas (solo se ven si el usuario elige «Modo experto»).
  - en_pruebas=True: esta hecha pero apagada hasta que termine la bateria de pruebas. Solo se puede encender en
    modo experto y avisando. Cuando la funcion pase las pruebas, se cambia a False aqui y ya esta.

Uso desde el codigo:   funciones.activa("bloqueo_atacantes")   funciones.opcion("bloqueo_atacantes", "intentos")
"""
from __future__ import annotations

import ipaddress
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GRUPOS = [
    ("copias", "Copias", "Cómo y cuándo se hacen las copias y qué hace OCTOPUS solo."),
    ("ataques", "Ataques (ransomware)", "Qué hace OCTOPUS cuando detecta que están cifrando archivos."),
    ("acceso", "Seguridad del panel", "Quién puede entrar al panel y desde dónde."),
    ("identidad", "Usuarios de la empresa", "Entrar al panel con los usuarios que ya tiene la empresa."),
    ("equipos", "Equipos", "Dar de alta, instalar y levantar equipos."),
]


def _servidor_mac() -> tuple[bool, str]:
    if platform.system() == "Darwin":
        return False, "El servidor está en un Mac: macOS no deja servir arranque por red (PXE). Hace falta un servidor Linux."
    return True, ""


def _servidor_windows() -> tuple[bool, str]:
    if platform.system() == "Windows":
        return False, ("El servidor está en Windows: el arranque por red de OCTOPUS necesita un servidor Linux "
                       "(Windows ya tiene su propio WDS para eso).")
    return True, ""


def _pxe_disponible() -> tuple[bool, str]:
    for f in (_servidor_mac, _servidor_windows):
        ok, motivo = f()
        if not ok:
            return ok, motivo
    return True, ""


# Cada opcion: (clave, nombre, tipo, defecto, nivel, ayuda, extra). tipo: bool | int | texto | redes | eleccion
FUNCIONES: list[dict] = [
    # ------------------------------------------------------------------------------------------- copias
    {"clave": "autoarreglo", "grupo": "copias", "nivel": "basico", "defecto": True,
     "nombre": "Arreglar solo lo que no tiene riesgo",
     "explica": "Repetir copias que fallaron, quitar bloqueos del almacén, renovar el certificado... Lo que podría "
                "borrar datos siempre pide permiso con un botón."},
    {"clave": "actualizar_solo", "grupo": "copias", "nivel": "basico", "defecto": True,
     "nombre": "Actualizar OCTOPUS solo (de madrugada)",
     "explica": "Instala solo las versiones nuevas firmadas, por la noche. Apágalo si no quieres que se actualice solo."},
    {"clave": "informe_mensual", "grupo": "copias", "nivel": "basico", "defecto": True,
     "nombre": "Informe mensual por correo",
     "explica": "El día 1 de cada mes llega un resumen de cómo han ido las copias."},
    {"clave": "senuelos", "grupo": "copias", "nivel": "basico", "defecto": True,
     "nombre": "Archivos trampa (señuelos)",
     "explica": "Un archivo oculto en cada carpeta protegida: si alguien lo cifra o lo borra, es un ataque seguro."},
    {"clave": "periodo_prueba", "grupo": "copias", "nivel": "basico", "defecto": True,
     "nombre": "Periodo de aprendizaje en equipos nuevos",
     "explica": "Los primeros días de un equipo nuevo, si la detección ve algo raro solo avisa en amarillo (no aísla), "
                "mientras aprende lo que es normal en ese equipo. Los archivos trampa siguen actuando siempre.",
     "opciones": [("dias", "Días de aprendizaje", "int", 7, "experto", "", {"min": 1, "max": 60})]},

    # ------------------------------------------------------------------------------------------- ataques
    {"clave": "incident_auto_response", "grupo": "ataques", "nivel": "basico", "defecto": True,
     "nombre": "Responder solo a un ataque",
     "explica": "Aislar el equipo, guardar las pruebas, preparar la recuperación y avisar, sin esperar a nadie."},
    {"clave": "incident_keep_isolated", "grupo": "ataques", "nivel": "experto", "defecto": True,
     "nombre": "Mantener aislado hasta que se revise",
     "explica": "El equipo atacado sigue aislado de la red hasta que alguien lo libere desde el panel."},
    {"clave": "sandbox_terminal", "grupo": "ataques", "nivel": "experto", "defecto": True,
     "nombre": "Consola en la sala de análisis",
     "explica": "Permite a los administradores ejecutar comandos en la sala de análisis de un incidente."},

    # ------------------------------------------------------------------------------------------- acceso
    {"clave": "aviso_acceso_nuevo", "grupo": "acceso", "nivel": "basico", "defecto": True,
     "nombre": "Avisar si alguien entra desde un sitio nuevo",
     "explica": "Si alguien entra al panel desde un navegador o una dirección que no se había usado antes, llega un aviso "
                "(correo y Telegram) para que sepas si has sido tú."},
    {"clave": "bloqueo_atacantes", "grupo": "acceso", "nivel": "basico", "defecto": True, "en_pruebas": True,
     "nombre": "Bloquear a quien prueba contraseñas",
     "explica": "Una dirección que falla muchas veces la contraseña (o prueba páginas que no existen) se bloquea un rato. "
                "Las direcciones de confianza nunca se bloquean.",
     "opciones": [("intentos", "Fallos antes de bloquear", "int", 10, "experto", "", {"min": 3, "max": 100}),
                  ("minutos", "Minutos de bloqueo", "int", 30, "experto", "", {"min": 1, "max": 1440}),
                  ("confianza", "Direcciones de confianza (nunca se bloquean)", "redes", "", "experto",
                   "Por ejemplo 192.168.1.0/24, 10.0.0.5", {})]},
    {"clave": "panel_solo_redes", "grupo": "acceso", "nivel": "experto", "defecto": False, "en_pruebas": True,
     "nombre": "Panel solo desde la red de la oficina (o VPN)",
     "explica": "Desde cualquier otra dirección el panel no responde. Los equipos siguen haciendo sus copias igual. "
                "La red desde la que estás ahora se añade sola, para que no te quedes fuera.",
     "opciones": [("redes", "Redes permitidas", "redes", "", "experto", "Por ejemplo 192.168.1.0/24, 10.8.0.0/24", {})]},
    {"clave": "doble_aprobacion", "grupo": "acceso", "nivel": "experto", "defecto": False, "en_pruebas": True,
     "nombre": "Doble aprobación para lo peligroso",
     "explica": "Borrar un equipo, cambiar cuánto tiempo se guardan las copias o apagar los avisos necesita que lo "
                "apruebe otro administrador. Necesita al menos dos administradores.",
     "opciones": [("horas", "Horas para aprobar antes de caducar", "int", 24, "experto", "", {"min": 1, "max": 168})]},

    # ------------------------------------------------------------------------------------------- identidad
    {"clave": "ldap", "grupo": "identidad", "nivel": "experto", "defecto": False, "en_pruebas": True,
     "nombre": "Active Directory / LDAP",
     "explica": "Entrar con el usuario y la contraseña del dominio de Windows. El usuario local de OCTOPUS sigue "
                "funcionando siempre como entrada de emergencia.",
     "opciones": [("servidor", "Servidor (ldaps://dc1.empresa.local)", "texto", "", "experto", "", {}),
                  ("base", "Base de búsqueda (DC=empresa,DC=local)", "texto", "", "experto", "", {}),
                  ("usuario_lectura", "Usuario de lectura (opcional)", "texto", "", "experto",
                   "Si se deja vacío, se busca con el propio usuario que entra", {}),
                  ("password_lectura", "Contraseña del usuario de lectura", "secreto", "", "experto", "", {}),
                  ("grupo_admin", "Grupo de administradores", "texto", "OCTOPUS-Admin", "experto", "", {}),
                  ("grupo_recuperar", "Grupo que solo recupera archivos", "texto", "OCTOPUS-Recuperar", "experto", "", {}),
                  ("grupo_lectura", "Grupo de solo lectura", "texto", "OCTOPUS-Lectura", "experto", "", {})]},
    {"clave": "oidc", "grupo": "identidad", "nivel": "experto", "defecto": False, "en_pruebas": True,
     "nombre": "Entrar con Microsoft 365, Google, Authentik o Keycloak (OIDC)",
     "explica": "Botón «Entrar con...» en la pantalla de acceso. El usuario local sigue funcionando siempre.",
     "opciones": [("nombre_boton", "Texto del botón", "texto", "Entrar con la cuenta de la empresa", "experto", "", {}),
                  ("emisor", "Dirección del proveedor (issuer)", "texto", "", "experto",
                   "Ej.: https://login.microsoftonline.com/<tenant>/v2.0", {}),
                  ("cliente", "ID de cliente", "texto", "", "experto", "", {}),
                  ("secreto", "Secreto de cliente", "secreto", "", "experto", "", {}),
                  ("campo_grupos", "Campo con los grupos", "texto", "groups", "experto", "", {}),
                  ("grupo_admin", "Grupo de administradores", "texto", "OCTOPUS-Admin", "experto", "", {}),
                  ("grupo_recuperar", "Grupo que solo recupera archivos", "texto", "OCTOPUS-Recuperar", "experto", "", {}),
                  ("grupo_lectura", "Grupo de solo lectura", "texto", "OCTOPUS-Lectura", "experto", "", {})]},
    {"clave": "radius", "grupo": "identidad", "nivel": "experto", "defecto": False, "en_pruebas": True,
     "nombre": "RADIUS (FreeRADIUS, NPS de Windows...)",
     "explica": "Comprobar usuario y contraseña contra un servidor RADIUS. El usuario local sigue funcionando siempre.",
     "opciones": [("servidor", "Servidor RADIUS (IP o nombre)", "texto", "", "experto", "", {}),
                  ("puerto", "Puerto", "int", 1812, "experto", "", {"min": 1, "max": 65535}),
                  ("secreto", "Secreto compartido", "secreto", "", "experto", "", {}),
                  ("rol", "Papel de quien entra por RADIUS", "eleccion", "lectura", "experto", "",
                   {"valores": [("admin", "Administrador"), ("recuperar", "Solo recuperar archivos"),
                                ("lectura", "Solo ver")]})]},

    # ------------------------------------------------------------------------------------------- equipos
    {"clave": "buscar_equipos", "grupo": "equipos", "nivel": "basico", "defecto": True,
     "nombre": "Buscar equipos en la red",
     "explica": "Botón para encontrar los equipos de la red y protegerlos en grupo."},
    {"clave": "usb_rescate", "grupo": "equipos", "nivel": "basico", "defecto": False, "en_pruebas": True,
     "nombre": "USB de rescate",
     "explica": "Crear un pendrive que arranca un equipo que ya no enciende Windows o Linux y lo deja como estaba, "
                "desde su copia completa. No sirve para Mac (Apple no deja arrancar otros sistemas en los Mac modernos).",
     "no_mac": True},
    {"clave": "imagen_disco", "grupo": "equipos", "nivel": "experto", "defecto": False, "en_pruebas": True,
     "nombre": "Copia «imagen de disco»",
     "explica": "Además de los archivos, una copia del disco entero en bloque, para clonarlo tal cual en otro disco. "
                "Ocupa más. No disponible en Mac.", "no_mac": True},
    {"clave": "arranque_red", "grupo": "equipos", "nivel": "experto", "defecto": False, "en_pruebas": True,
     "nombre": "Arranque por red (PXE)",
     "explica": "Los equipos arrancan desde el servidor pulsando F12, sin pendrive, y aparecen en el panel para "
                "recuperarlos o instalarlos. Necesita un servidor Linux.", "disponible": _pxe_disponible, "no_mac": True},
    {"clave": "despliegue_masa", "grupo": "equipos", "nivel": "experto", "defecto": False, "en_pruebas": True,
     "nombre": "Desplegar el mismo sistema en muchos equipos",
     "explica": "Llevar una instalación de referencia (Windows preparado con sysprep, o Linux) a muchos equipos a la vez "
                "por la red. En Mac no se puede: Apple solo lo permite con su gestión de dispositivos (MDM).",
     "requiere": "arranque_red", "no_mac": True},
]

MOTIVO_MAC = ("No disponible en Mac: Apple no permite clonar ni arrancar por red los Mac modernos (chip Apple o T2). "
              "Para muchos Mac se usa Apple Business Manager con un MDM y «Borrar contenidos y ajustes».")

_POR_CLAVE = {f["clave"]: f for f in FUNCIONES}


def defectos() -> dict:
    """Ajustes por defecto de todas las funciones y sus opciones (para config_manager)."""
    d = {}
    for f in FUNCIONES:
        d[f["clave"]] = bool(f["defecto"]) and not f.get("en_pruebas")
        for o in f.get("opciones", []):
            d[f"{f['clave']}.{o[0]}"] = o[3]
    d["funciones_en_pruebas_aceptadas"] = []
    return d


def _cm():
    import config_manager
    import os
    base = Path(__file__).resolve().parent.parent
    db = os.environ.get("DB_PATH") or os.environ.get("OCTOPUS_DB") or ""
    if not db:
        try:
            import configuracion
            db = configuracion.leer_env().get("DB_PATH", "./data/admin_panel.db")
        except Exception:
            db = "./data/admin_panel.db"
    db = db if os.path.isabs(db) else str((base / db).resolve())
    return config_manager.ConfigManager(db)


_gestor = None


def usar(gestor) -> None:
    """El panel le pasa su propio gestor de ajustes (la misma base de datos)."""
    global _gestor
    _gestor = gestor


def _leer(clave: str):
    global _gestor
    if _gestor is None:
        _gestor = _cm()
    return _gestor.get_config(clave)


def disponible(clave: str) -> tuple[bool, str]:
    f = _POR_CLAVE[clave]
    if "disponible" in f:
        return f["disponible"]()
    return True, ""


def activa(clave: str) -> bool:
    """¿Está encendida? (y disponible en este servidor). Lo que esta en pruebas solo si alguien lo encendio a sabiendas."""
    f = _POR_CLAVE.get(clave)
    if not f:
        return False
    try:
        valor = _leer(clave)
    except Exception:
        valor = None
    if valor is None:
        valor = defectos()[clave]
    if not valor or not disponible(clave)[0]:
        return False
    if f.get("requiere") and not activa(f["requiere"]):
        return False
    return bool(valor)


def opcion(clave: str, nombre: str):
    f = _POR_CLAVE[clave]
    o = next(o for o in f.get("opciones", []) if o[0] == nombre)
    try:
        v = _leer(f"{clave}.{nombre}")
    except Exception:
        v = None
    return o[3] if v is None else v


def para_equipo(clave: str, so: str) -> tuple[bool, str]:
    """¿Se puede usar esta funcion en un equipo de este sistema? (False, motivo) para Mac en lo que Apple no deja."""
    f = _POR_CLAVE[clave]
    if so == "macos" and f.get("no_mac"):
        return False, MOTIVO_MAC
    if not activa(clave):
        return False, ("Está en pruebas: se podrá usar cuando termine la batería de pruebas."
                       if f.get("en_pruebas") else "Está apagada en Ajustes → Funciones.")
    return True, ""


# ----------------------------------------------------------------------------- validar lo que escribe el usuario
def validar(tipo: str, texto: str, extra: dict):
    """Convierte lo escrito al tipo de la opcion. ValueError con un mensaje claro si no vale."""
    texto = (texto or "").strip()
    if tipo == "int":
        try:
            n = int(texto)
        except ValueError:
            raise ValueError("tiene que ser un número entero") from None
        if "min" in extra and n < extra["min"] or "max" in extra and n > extra["max"]:
            raise ValueError(f"tiene que estar entre {extra.get('min')} y {extra.get('max')}")
        return n
    if tipo == "redes":
        redes = []
        for r in texto.replace(";", ",").split(","):
            if r.strip():
                try:
                    redes.append(str(ipaddress.ip_network(r.strip(), strict=False)))
                except ValueError:
                    raise ValueError(f"«{r.strip()}» no es una red ni una IP válida") from None
        return ", ".join(redes)
    if tipo == "eleccion":
        if texto not in [v for v, _ in extra.get("valores", [])]:
            raise ValueError("elige una de las opciones")
        return texto
    if tipo in ("texto", "secreto"):
        if len(texto) > 500:
            raise ValueError("es demasiado largo")
        return texto
    raise ValueError("tipo desconocido")


def en_redes(ip: str, redes: str) -> bool:
    try:
        dir_ip = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for r in (redes or "").split(","):
        if r.strip():
            try:
                if dir_ip in ipaddress.ip_network(r.strip(), strict=False):
                    return True
            except ValueError:
                continue
    return False
