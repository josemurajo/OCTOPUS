#!/usr/bin/env python3
"""
OCTOPUS - Catalogo unico de avisos: cada problema tiene un CODIGO, que pasa, por que importa, los pasos
exactos para solucionarlo y, cuando se puede, una accion automatica (boton "Solucionar" del panel).

El mismo codigo aparece en el panel, en los correos/Telegram y en los banderines, asi siempre se sabe de que
se habla. Las acciones del servidor (almacen, certificado, mantenimiento...) estan aqui; las de un equipo
(volver a copiar, repetir la prueba) las ejecuta el panel porque necesitan hablar con el agente.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
DATA = BASE_DIR / "data"
ACTUALIZACION_FILE = DATA / "actualizacion.json"
REINICIAR_FLAG = Path(os.environ.get("OCTOPUS_DATA", "/data")) / "reiniciar_servicios"

_REINICIO_AGENTE = ("Si sigue igual, reinicia el agente en ese equipo: en Windows, Programador de tareas → "
                    "«OCTOPUS Agente» → Ejecutar; en Linux, sudo systemctl restart octopus-agent; en Mac, "
                    "sudo launchctl kickstart -k system/com.octopus.agent.")

# codigo -> datos. En los textos, {equipo} y {detalle} se rellenan con el caso concreto.
CATALOGO: dict[str, dict] = {
    # ---------------------------------------------------------------- equipos
    "OCT-EQ-01": {
        "nivel": "problema", "titulo": "No hay conexión con {equipo}",
        "por_que": "Mientras no haya conexión no se hacen copias de este equipo y no se le puede proteger si le atacan.",
        "pasos": ["Comprueba que el equipo está encendido y conectado a la red (y que no está en suspensión).",
                  "Si se acaba de reiniciar, espera 2 minutos: el agente vuelve a conectar solo.",
                  _REINICIO_AGENTE,
                  "Si nada de eso funciona, vuelve a instalar el agente desde la ficha del equipo (no se pierden copias)."],
        "accion": None},
    "OCT-EQ-02": {
        "nivel": "atencion", "titulo": "{equipo} todavía no tiene ninguna copia",
        "por_que": "Si este equipo se estropea o le atacan hoy, no habría nada que recuperar.",
        "pasos": ["Pulsa «Solucionar» (o «Hacer copia ahora» en la ficha del equipo).",
                  "La primera copia puede tardar un rato; luego son mucho más rápidas."],
        "accion": "copia_equipo", "boton": "Hacer la copia ahora"},
    "OCT-EQ-03": {
        "nivel": "atencion", "titulo": "La última copia de {equipo} es de {detalle}",
        "por_que": "Lo que se haya creado o cambiado desde entonces no está protegido.",
        "pasos": ["Si el equipo estuvo apagado o de viaje, es normal: pulsa «Solucionar» para copiar ahora.",
                  "Si estaba encendido, revisa que tenga conexión; la copia diaria se hace sola cada día.",
                  "Para portátiles que pasan días fuera, puedes ampliar el plazo en su ficha («Aviso si se queda sin copia»)."],
        "accion": "copia_equipo", "boton": "Hacer la copia ahora"},
    "OCT-EQ-04": {
        "nivel": "problema", "titulo": "La última copia de {equipo} falló",
        "por_que": "Este equipo se ha quedado sin copia reciente.",
        "pasos": ["Pulsa «Solucionar» para repetirla (muchas veces es algo puntual: red, equipo en uso...).",
                  "Si vuelve a fallar, comprueba que el equipo tiene espacio libre y conexión con el servidor.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": "copia_equipo", "boton": "Repetir la copia"},
    "OCT-EQ-05": {
        "nivel": "problema", "titulo": "La prueba de recuperación de {equipo} falló",
        "por_que": "No se ha podido comprobar que sus copias se recuperan bien; podría fallar justo cuando haga falta.",
        "pasos": ["Pulsa «Solucionar»: se hace una copia nueva del equipo y se repite la prueba.",
                  "Si vuelve a fallar, revisa el aviso del almacén (si lo hay) y avisa al técnico.",
                  "Detalle: {detalle}"],
        "accion": "prueba_equipo", "boton": "Copiar y volver a probar"},
    "OCT-EQ-06": {
        "nivel": "atencion", "titulo": "La última copia de {equipo} se hizo durante un ataque",
        "por_que": "Esa copia puede contener archivos cifrados o dañados.",
        "pasos": ["Si tienes que recuperar algo, usa una copia limpia (en la ficha del equipo se ve cuál es).",
                  "Cuando el equipo esté limpio, haz una copia nueva."],
        "accion": None},
    "OCT-SEN-01": {
        "nivel": "problema", "titulo": "Alguien ha tocado un archivo señuelo en {equipo}",
        "por_que": "Los archivos señuelo no los usa nadie: si cambian, casi seguro es un ataque (ransomware).",
        "pasos": ["Abre el incidente en «Incidentes» y sigue los pasos (aislar el equipo, recuperar la última copia limpia).",
                  "No apagues el equipo a la fuerza: OCTOPUS ya ha guardado evidencias.",
                  "Detalle: {detalle}"],
        "accion": None},
    # ---------------------------------------------------------------- almacen y servidor
    "OCT-ALM-01": {
        "nivel": "problema", "titulo": "El almacén de copias se ha quedado bloqueado",
        "por_que": "Suele pasar tras un corte de luz o un reinicio a mitad de una tarea. Mientras siga bloqueado, "
                   "la limpieza y la comprobación del almacén no se hacen.",
        "pasos": ["Pulsa «Solucionar»: se quitan los bloqueos antiguos (no se borra ninguna copia) y se comprueba el almacén.",
                  "Si vuelve a pasar a menudo, revisa que el servidor no se apague de golpe (un SAI ayuda)."],
        "accion": "desbloquear_almacen", "boton": "Quitar el bloqueo"},
    "OCT-ALM-02": {
        "nivel": "problema", "titulo": "La comprobación del almacén de copias ha encontrado errores",
        "por_que": "Alguna copia podría no recuperarse bien.",
        "pasos": ["No borres nada.",
                  "Pulsa «Solucionar»: se repara el índice del almacén y se vuelve a comprobar.",
                  "Si sigue con errores, revisa el disco del servidor y avisa al técnico. Si tienes almacén externo, "
                  "tus copias siguen allí.",
                  "Detalle: {detalle}"],
        "accion": "reparar_almacen", "boton": "Reparar y comprobar"},
    "OCT-ALM-03": {
        "nivel": "atencion", "titulo": "La limpieza de copias antiguas no se pudo hacer",
        "por_que": "Si no se limpian, el disco del servidor se va llenando.",
        "pasos": ["Pulsa «Solucionar» para repetirla ahora.",
                  "Si falla otra vez, comprueba el espacio libre del servidor.",
                  "Detalle: {detalle}"],
        "accion": "limpiar_copias", "boton": "Limpiar ahora"},
    "OCT-DISCO-01": {
        "nivel": "problema", "titulo": "El disco del almacén está casi lleno",
        "por_que": "Si se llena, las copias nuevas dejarán de hacerse.",
        "pasos": ["Pulsa «Solucionar»: se borran las copias que ya no hacen falta según cuántas has elegido guardar.",
                  "Si sigue casi lleno, guarda menos copias (Ajustes → Copias e informes) o amplía el disco del servidor.",
                  "Detalle: {detalle}"],
        "accion": "limpiar_copias", "boton": "Liberar espacio"},
    "OCT-SRV-01": {
        "nivel": "problema", "titulo": "La copia del propio servidor ha fallado",
        "por_que": "Sin ella, si se pierde el servidor sería más difícil recuperarlo todo.",
        "pasos": ["Pulsa «Solucionar» para repetirla ahora.",
                  "Si usas almacén externo, comprueba la conexión a Internet y que sus claves siguen siendo válidas "
                  "(sudo bash octopus.sh ajustes).",
                  "Detalle: {detalle}"],
        "accion": "copia_servidor", "boton": "Repetir la copia del servidor"},
    "OCT-SRV-02": {
        "nivel": "problema", "titulo": "El mantenimiento nocturno no se ha hecho",
        "por_que": "Es el que limpia copias viejas, comprueba el almacén, hace la copia del servidor y prueba recuperaciones.",
        "pasos": ["Pulsa «Solucionar» para hacerlo ahora (tarda unos minutos; el resultado sale en Ajustes).",
                  "Si el servidor estuvo apagado por la noche, es normal; déjalo encendido.",
                  "Detalle: {detalle}"],
        "accion": "mantenimiento_ahora", "boton": "Hacer el mantenimiento ahora"},
    "OCT-SRV-03": {
        "nivel": "atencion", "titulo": "El informe mensual no se pudo enviar",
        "por_que": "No te llegará el resumen del mes por correo (el informe se puede ver igualmente en Ajustes).",
        "pasos": ["Revisa el correo de avisos en Ajustes → Avisos por correo y pulsa «Enviar prueba».",
                  "Detalle: {detalle}"],
        "accion": None},
    "OCT-CERT-01": {
        "nivel": "atencion", "titulo": "El certificado de seguridad del servidor caduca pronto",
        "por_que": "Cuando caduque, los equipos dejarán de conectar con el servidor.",
        "pasos": ["Pulsa «Solucionar»: se emite uno nuevo con la misma autoridad (los equipos lo aceptan sin tocarlos) "
                  "y el panel se reinicia unos segundos.",
                  "Detalle: {detalle}"],
        "accion": "renovar_certificado", "boton": "Renovar el certificado"},
    "OCT-KIT-01": {
        "nivel": "atencion", "titulo": "Todavía no has descargado el kit de recuperación",
        "por_que": "Sin él, si se pierde este servidor nadie podría abrir las copias.",
        "pasos": ["Ve a Ajustes → Kit de recuperación y descárgalo.",
                  "Guárdalo fuera del servidor: pendrive, gestor de contraseñas o en papel en un sitio seguro."],
        "accion": None, "enlace": "ajustes#kit"},
    "OCT-ACT-01": {
        "nivel": "atencion", "titulo": "Hay una versión nueva de OCTOPUS ({detalle})",
        "por_que": "Las versiones nuevas traen arreglos y mejoras de seguridad.",
        "pasos": ["Normalmente se instala sola por la noche. Si ves este aviso es porque las actualizaciones automáticas "
                  "están en pausa, o porque no se pudo instalar sola: ve a Ajustes → Actualizaciones y pulsa «Actualizar ahora» "
                  "(el servidor la descarga, comprueba que está firmada por OCTOPUS y la instala; si algo va mal, vuelve "
                  "solo a la versión actual).",
                  "Si ese botón dice que el actualizador no está activado (servidores Windows), en el servidor: "
                  "sudo bash octopus.sh actualizar (en Windows: octopus.ps1 actualizar). Se conservan los datos y las copias.",
                  "Pulsa «Solucionar» para volver a comprobar si ya estás al día."],
        "accion": "comprobar_actualizacion", "boton": "Volver a comprobar"},
    "OCT-SUG-01": {
        "nivel": "atencion", "titulo": "Hay sugerencias o problemas sin enviar al soporte",
        "por_que": "Se guardaron porque no había a dónde enviarlos o no había conexión.",
        "pasos": ["Pulsa «Solucionar» para intentar enviarlos otra vez.",
                  "Si no hay ningún destino de soporte configurado, se quedan guardados en el servidor."],
        "accion": "reenviar_sugerencias", "boton": "Reintentar el envío"},
}


def ficha(codigo: str, **datos) -> dict:
    """El aviso completo y ya rellenado para un caso concreto."""
    c = dict(CATALOGO.get(codigo) or {"nivel": "atencion", "titulo": codigo, "por_que": "", "pasos": [], "accion": None})
    datos = {k: ("" if v is None else v) for k, v in datos.items()}
    datos.setdefault("equipo", "")
    datos.setdefault("detalle", "")

    def rellenar(t: str) -> str:
        try:
            return t.format(**datos)
        except (KeyError, IndexError, ValueError):
            return t
    pasos = [rellenar(p) for p in c.get("pasos", [])]
    if not datos["detalle"]:
        pasos = [p for p in pasos if not p.rstrip().endswith(":")]
    return {"codigo": codigo, "nivel": c["nivel"], "titulo": rellenar(c["titulo"]), "por_que": c.get("por_que", ""),
            "pasos": pasos, "accion": c.get("accion"), "boton": c.get("boton", "Solucionar"),
            "enlace": c.get("enlace")}


def texto(codigo: str, **datos) -> str:
    """El aviso en texto plano (correo, Telegram, registro)."""
    f = ficha(codigo, **datos)
    lineas = [f"[{codigo}] {f['titulo']}", f"Por qué importa: {f['por_que']}", "Qué hacer:"]
    lineas += [f"  {i}. {p}" for i, p in enumerate(f["pasos"], 1)]
    if f["accion"]:
        try:
            import autoarreglo as _aa
            auto, riesgo = _aa.es_automatica(f["accion"]), _aa.riesgo(f["accion"])
        except Exception:
            auto, riesgo = False, None
        if auto:
            lineas.append("  (No tiene riesgo: OCTOPUS lo está arreglando solo. Si tienes prisa, en el panel, Avisos, "
                          "pulsa «Solucionar».)")
        elif riesgo:
            lineas.append(f"  (Necesita tu permiso porque puede borrar datos: {riesgo} Para hacerlo, en el panel, "
                          f"Avisos, pulsa «Solucionar» y confírmalo.)")
        else:
            lineas.append("  (En el panel, en Avisos, hay un botón «Solucionar» que lo hace solo.)")
    return "\n".join(lineas)


# ---------------------------------------------------------------- comprobaciones del servidor
def codigo_mantenimiento(tarea: str, resultado: dict) -> str | None:
    """Codigo del aviso para una tarea del mantenimiento que ha fallado."""
    det = str(resultado.get("detalle") or "").lower()
    if tarea == "verificar":
        return "OCT-ALM-01" if "lock" in det else "OCT-ALM-02"
    if tarea == "retencion":
        return "OCT-ALM-01" if "lock" in det else "OCT-ALM-03"
    if tarea == "vigilar":
        return "OCT-DISCO-01" if resultado.get("disco_lleno") else None
    return {"autocopia": "OCT-SRV-01", "informe": "OCT-SRV-03"}.get(tarea)


def caducidad_certificado() -> int | None:
    """Dias que le quedan al certificado del servidor (None si no se puede saber)."""
    crt = DATA / "tls" / "panel.crt"
    if not crt.is_file():
        return None
    try:
        r = subprocess.run(["openssl", "x509", "-enddate", "-noout", "-in", str(crt)],
                           capture_output=True, text=True, timeout=20)
        fin = datetime.strptime(r.stdout.strip().split("=", 1)[1], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        return int((fin - datetime.now(timezone.utc)).total_seconds() // 86400)
    except (OSError, IndexError, ValueError, subprocess.SubprocessError):
        return None


def mantenimiento_atrasado(estado: dict, db_file: Path | None = None) -> str | None:
    """Texto si el mantenimiento nocturno lleva mas de 36 h sin hacerse; None si va bien."""
    fecha = estado.get("fecha")
    if fecha:
        try:
            t = datetime.fromisoformat(fecha)
            horas = (datetime.now(t.tzinfo or timezone.utc) - t).total_seconds() / 3600
            return f"el último fue hace {int(horas)} horas" if horas > 36 else None
        except ValueError:
            return None
    # nunca se ha hecho: solo se avisa si el servidor ya lleva mas de 36 h instalado
    try:
        if db_file and db_file.is_file() and time.time() - db_file.stat().st_mtime > 0:
            creado = min(db_file.stat().st_ctime, db_file.stat().st_mtime)
            if time.time() - creado > 36 * 3600 and not (DATA / "mantenimiento.json").exists():
                return "todavía no se ha hecho ninguno"
    except OSError:
        pass
    return None


def version_local() -> str:
    for f in (BASE_DIR / "VERSION",):
        try:
            return f.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return os.environ.get("OCTOPUS_VERSION", "")


def _num(v: str) -> tuple:
    partes = []
    for p in str(v).strip().lstrip("vV").split("."):
        try:
            partes.append(int("".join(ch for ch in p if ch.isdigit()) or 0))
        except ValueError:
            partes.append(0)
    return tuple(partes)


def comprobar_actualizacion(timeout: float = 15) -> dict:
    """Mira la ultima version publicada (archivo VERSION del repositorio). Se guarda para el panel.
    Se puede desactivar con OCTOPUS_COMPROBAR_ACTUALIZACIONES=no o cambiar la URL con OCTOPUS_URL_VERSION."""
    import urllib.request
    cfg = dict(os.environ)
    try:
        import mantenimiento as _m
        cfg.update(_m.leer_env())
    except Exception:
        pass
    if cfg.get("OCTOPUS_COMPROBAR_ACTUALIZACIONES", "si").lower() in ("no", "0", "false"):
        return {"ok": True, "hay_nueva": False, "detalle": "comprobación desactivada"}
    url = cfg.get("OCTOPUS_URL_VERSION") or "https://raw.githubusercontent.com/josemurajo/OCTOPUS/main/VERSION"
    local = version_local()
    res = {"fecha": datetime.now().astimezone().isoformat(timespec="seconds"), "local": local}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "octopus"}),
                                    timeout=timeout) as r:
            remota = r.read(64).decode("utf-8", "replace").strip()
        res.update(remota=remota, hay_nueva=bool(local and remota and _num(remota) > _num(local)))
        res["ok"] = True
        res["detalle"] = f"versión nueva {remota}" if res["hay_nueva"] else f"al día ({local})"
    except Exception as exc:  # sin Internet no es un fallo del servidor
        res.update(ok=True, hay_nueva=False, detalle=f"no se pudo comprobar ({exc.__class__.__name__})")
    try:
        ACTUALIZACION_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTUALIZACION_FILE.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return res


def leer_actualizacion() -> dict:
    try:
        act = json.loads(ACTUALIZACION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # si ya se ha actualizado desde la ultima comprobacion, deja de haber version nueva
    local = version_local()
    if act.get("hay_nueva") and local and _num(local) >= _num(act.get("remota", "")):
        act.update(hay_nueva=False, local=local, detalle=f"al día ({local})")
    return act


# ---------------------------------------------------------------- acciones automaticas del servidor
def _env_mant():
    import mantenimiento as m
    return m, m.leer_env()


def desbloquear_almacen() -> dict:
    m, env = _env_mant()
    partes, ok = [], True
    for cuarentena in (False, True):
        repo, pwd = m.repo_local(env, cuarentena)
        if not repo or not os.path.isdir(repo):
            continue
        e = m.restic_env(repo, pwd)
        m.run([m.restic_bin(), "unlock"], env=e, timeout=300)
        r = m.run([m.restic_bin(), "check"], env=e, timeout=3600)
        ok = ok and r.returncode == 0
        partes.append(f"{os.path.basename(repo)}: {'correcto' if r.returncode == 0 else 'sigue con errores'}")
    if not partes:
        return {"ok": False, "detalle": "No se encuentra el almacén en disco"}
    return {"ok": ok, "detalle": "Bloqueos quitados. " + "; ".join(partes)}


def reparar_almacen() -> dict:
    m, env = _env_mant()
    partes, ok = [], True
    for cuarentena in (False, True):
        repo, pwd = m.repo_local(env, cuarentena)
        if not repo or not os.path.isdir(repo):
            continue
        e = m.restic_env(repo, pwd)
        m.run([m.restic_bin(), "unlock"], env=e, timeout=300)
        rep = m.run([m.restic_bin(), "repair", "index"], env=e, timeout=6 * 3600)
        if rep.returncode != 0 and "unknown command" in (rep.stderr or "").lower():
            m.run([m.restic_bin(), "rebuild-index"], env=e, timeout=6 * 3600)
        r = m.run([m.restic_bin(), "check"], env=e, timeout=6 * 3600)
        ok = ok and r.returncode == 0
        partes.append(f"{os.path.basename(repo)}: {'correcto' if r.returncode == 0 else 'ERROR ' + (r.stderr or '')[-200:]}")
    if not partes:
        return {"ok": False, "detalle": "No se encuentra el almacén en disco"}
    return {"ok": ok, "detalle": "; ".join(partes)}


def limpiar_copias() -> dict:
    m, env = _env_mant()
    return m.retencion(env)


def copia_servidor() -> dict:
    m, env = _env_mant()
    return m.autocopia(env)


def mantenimiento_ahora() -> dict:
    log = DATA / "logs"
    log.mkdir(parents=True, exist_ok=True)
    with open(log / "mantenimiento.log", "a", encoding="utf-8") as fh:
        subprocess.Popen([sys.executable, str(BASE_DIR / "lib" / "mantenimiento.py"), "todo"],
                         cwd=str(BASE_DIR), stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    return {"ok": True, "detalle": "Mantenimiento en marcha. En unos minutos verás el resultado en Ajustes.",
            "en_marcha": True}


def renovar_certificado() -> dict:
    import configuracion
    tls = DATA / "tls"
    try:
        (tls / "nombres.txt").unlink(missing_ok=True)   # obliga a emitir uno nuevo (misma autoridad)
        configuracion.certificado_tls()
        configuracion.config_agentes()
    except Exception as exc:
        return {"ok": False, "detalle": f"No se pudo emitir el certificado: {exc}"}
    dias = caducidad_certificado()
    try:  # el arranque del contenedor reinicia el panel y el almacen para que usen el certificado nuevo
        REINICIAR_FLAG.write_text(str(time.time() + 3), encoding="utf-8")
    except OSError:
        pass
    return {"ok": bool(dias and dias > 30), "detalle": f"Certificado nuevo, válido {dias} días. El panel se reinicia "
                                                     f"en unos segundos: si no carga, recarga la página."}


def comprobar_actualizacion_ahora() -> dict:
    r = comprobar_actualizacion()
    return {"ok": not r.get("hay_nueva"), "detalle": "Sigue habiendo una versión nueva: actualiza siguiendo los pasos."
            if r.get("hay_nueva") else f"Comprobado: {r.get('detalle')}"}


ACCIONES_SERVIDOR = {
    "desbloquear_almacen": desbloquear_almacen,
    "reparar_almacen": reparar_almacen,
    "limpiar_copias": limpiar_copias,
    "copia_servidor": copia_servidor,
    "mantenimiento_ahora": mantenimiento_ahora,
    "renovar_certificado": renovar_certificado,
    "comprobar_actualizacion": comprobar_actualizacion_ahora,
}
