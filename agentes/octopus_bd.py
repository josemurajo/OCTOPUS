#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Copias de las BASES DE DATOS de un equipo (lo usa el agente, zerotouch_agent.py).

Copias «conscientes»: es el propio motor de la base de datos el que hace la copia (no se copian sus archivos a lo
bruto mientras se escriben), así que la copia SIEMPRE sirve para recuperar. Cada copia es una foto completa de la base
de datos a esa hora; con copias cada hora se puede volver a cualquier hora del día.

  SQL Server (Windows) ... BACKUP DATABASE ... WITH COPY_ONLY (no estropea las copias que ya haga la empresa), con
                           PowerShell y .NET (no hay que instalar nada). Se deja un .bak temporal en la carpeta de
                           copias del propio SQL Server, se guarda en el almacén y se borra.
  MySQL / MariaDB ........ mysqldump --single-transaction (no bloquea a quien está trabajando) → directo al almacén.
  PostgreSQL ............. pg_dump en formato propio → directo al almacén.

Recuperar: SIEMPRE como base de datos NUEVA (<nombre>_recuperada_<fecha>), al lado de la original, que no se toca.

Cómo entra en cada motor (sin pedir nada si se puede):
  MySQL/MariaDB  root por el «socket» local, o /etc/mysql/debian.cnf, o el usuario y contraseña puestos en el panel.
  PostgreSQL     como el usuario del sistema «postgres», o el usuario y contraseña puestos en el panel.
  SQL Server     con la cuenta del sistema (si tiene permiso) o el usuario de SQL puesto en el panel.

QUÉ TOCAR:
  - Otro motor ............... _<motor>_detectar(), _<motor>_copiar(), _<motor>_restaurar() y añadirlo a MOTORES.
  - Cómo se entra en un motor . _mysql_base(), _pg_base(), _sql_conexion().
  - Cuánto se guardan ........ lib/mantenimiento.py (retención de la etiqueta «bd»).
"""
from __future__ import annotations

import glob
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime

SYSTEM = platform.system().lower()
MOTORES = {"sqlserver": "SQL Server", "mysql": "MySQL / MariaDB", "postgresql": "PostgreSQL"}
SISTEMA_MYSQL = {"information_schema", "performance_schema", "mysql", "sys"}
SISTEMA_PG = {"postgres", "template0", "template1"}


# ------------------------------------------------------------------------------------------------ utilidades
def _run(cmd, timeout=600, env=None, entrada=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, input=entrada)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def etiqueta(txt: str) -> str:
    return re.sub(r"[,\s:]+", "_", str(txt)).strip("_")[:80] or "x"


def nombre_recuperada(nombre: str) -> str:
    """Nombre de la base recuperada: siempre distinto de la original (y válido en los tres motores)."""
    base = re.sub(r"[^A-Za-z0-9_]", "_", nombre)[:40] or "bd"
    return f"{base}_recuperada_{datetime.now():%Y%m%d%H%M}"


def _id_valido(nombre: str) -> bool:
    """Nombre de base de datos aceptable (sin caracteres que puedan colarse en una orden)."""
    return (bool(nombre) and len(nombre) <= 128 and not nombre.startswith("-")
            and not any(c in nombre for c in ("\x00", "`", "]", "'", '"', ";")))


def _archivo_seguro(nombre: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", nombre)[:80] or "bd"


def _resumen(stdout: str) -> str:
    snap = ""
    for linea in (stdout or "").splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if d.get("message_type") == "summary":
            snap = d.get("snapshot_id", "")
    return snap


def _tags(bd: dict) -> list[str]:
    return ["--tag", "octopus-agent", "--tag", "bd", "--tag", f"motor:{bd['motor']}",
            "--tag", f"bd:{bd['motor']}:{etiqueta(bd.get('instancia', ''))}:{etiqueta(bd['nombre'])}"]


def _a_restic_tuberia(ctx: dict, bd: dict, productor: list[str], env_prod: dict, archivo: str) -> dict:
    """Lanza el programa que vuelca la base de datos y lo mete DIRECTO en el almacén (sin archivo intermedio)."""
    try:
        p = subprocess.Popen(productor, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env_prod)
    except OSError as exc:
        return {"status": "error", "message": f"No se pudo lanzar {productor[0]}: {exc}"}
    cmd = [ctx["bin"], "backup", "--stdin", "--stdin-filename", archivo, *_tags(bd), "--host", ctx["host"], "--json",
           *ctx.get("opts", [])]
    try:
        r = subprocess.run(cmd, stdin=p.stdout, capture_output=True, text=True, timeout=12 * 3600, env=ctx["env"])
    finally:
        p.stdout.close()
        rc = p.wait()
        err = (p.stderr.read() or b"").decode(errors="replace")
    snap = _resumen(r.stdout)
    if rc != 0 or r.returncode != 0:
        if snap:     # copia a medias: fuera, para que nadie recupere una base de datos incompleta
            _run([ctx["bin"], "forget", snap], timeout=600, env=ctx["env"])
        return {"status": "error", "message": _explicar(err or r.stderr or "falló el volcado")}
    return {"status": "success", "snapshot_id": snap}


def _explicar(err: str) -> str:
    """El error del motor, con una frase que se entienda."""
    e = (err or "").strip()
    bajo = e.lower()
    if "access denied" in bajo or "permission denied" in bajo or "password authentication failed" in bajo \
            or "login failed" in bajo or "permiso" in bajo:
        return "No tengo permiso para entrar en la base de datos. En la pantalla de Bases de datos del panel te explica " \
               "cómo dármelo (un minuto). Detalle: " + e[-200:]
    if "no such file" in bajo or "can't connect" in bajo or "could not connect" in bajo or "connection refused" in bajo:
        return "La base de datos no responde (¿está arrancada?). Detalle: " + e[-200:]
    return e[-400:] or "Error desconocido"


# ------------------------------------------------------------------------------------------------ MySQL / MariaDB
def _mysql_base(cred: dict) -> tuple[list[str], dict, str]:
    """Argumentos y entorno para entrar en MySQL. Devuelve (args, env, error) probando de lo más cómodo a lo que pide clave."""
    env = dict(os.environ)
    c = cred.get("mysql") or {}
    socket = c.get("socket") or os.environ.get("OCTOPUS_MYSQL_SOCKET", "")
    extra = [f"--socket={socket}"] if socket else []
    if c.get("host"):
        extra += [f"--host={c['host']}"] + ([f"--port={c['port']}"] if c.get("port") else [])
    intentos = []
    if c.get("usuario"):
        e2 = dict(env, MYSQL_PWD=str(c.get("clave", "")))
        intentos.append(([f"--user={c['usuario']}", *extra], e2))
    intentos.append((["--user=root", *extra], env))
    if os.path.exists("/etc/mysql/debian.cnf"):
        intentos.append((["--defaults-file=/etc/mysql/debian.cnf", *extra], env))
    cliente = shutil.which("mysql") or shutil.which("mariadb")
    if not cliente:
        return [], env, "No está el programa mysql en este equipo"
    ultimo = ""
    for args, e in intentos:
        r = _run([cliente, *args, "-NBe", "SELECT 1"], timeout=30, env=e)
        if r.returncode == 0:
            return args, e, ""
        ultimo = r.stderr
    return [], env, _explicar(ultimo)


def _mysql_hay() -> bool:
    return bool((shutil.which("mysqldump") or shutil.which("mariadb-dump")) and (shutil.which("mysql") or shutil.which("mariadb")))


def _mysql_detectar(cred: dict) -> dict:
    if not _mysql_hay():
        return {}
    args, env, error = _mysql_base(cred)
    if error:
        return {"motor": "mysql", "acceso": "sin_permiso", "mensaje": error, "bases": []}
    cliente = shutil.which("mysql") or shutil.which("mariadb")
    r = _run([cliente, *args, "-NBe", "SELECT table_schema, COALESCE(SUM(data_length+index_length),0) FROM "
                                     "information_schema.tables GROUP BY table_schema"], timeout=120, env=env)
    tam = {}
    for linea in (r.stdout or "").splitlines():
        p = linea.split("\t")
        if len(p) == 2:
            tam[p[0]] = int(float(p[1] or 0))
    r = _run([cliente, *args, "-NBe", "SHOW DATABASES"], timeout=60, env=env)
    bases = [{"motor": "mysql", "instancia": "local", "nombre": n, "tamano": tam.get(n, 0)}
             for n in (r.stdout or "").split() if n not in SISTEMA_MYSQL]
    return {"motor": "mysql", "acceso": "ok", "mensaje": "", "bases": bases}


def _mysqldump_flags() -> list[str]:
    exe = shutil.which("mysqldump") or shutil.which("mariadb-dump")
    v = _run([exe, "--version"], timeout=30).stdout.lower()
    flags = ["--single-transaction", "--quick", "--routines", "--triggers", "--events", "--hex-blob", "--no-tablespaces"]
    if "mariadb" not in v:
        flags.append("--set-gtid-purged=OFF")
    return flags


def _mysql_copiar(ctx: dict, bd: dict) -> dict:
    args, env, error = _mysql_base(ctx.get("cred", {}))
    if error:
        return {"status": "error", "message": error}
    exe = shutil.which("mysqldump") or shutil.which("mariadb-dump")
    return _a_restic_tuberia(ctx, bd, [exe, *args, *_mysqldump_flags(), bd["nombre"]], env,
                             f"mysql-{etiqueta(bd['nombre'])}.sql")


def _mysql_restaurar(ctx: dict, snap: str, bd: dict, archivo: str, nuevo: str) -> dict:
    args, env, error = _mysql_base(ctx.get("cred", {}))
    if error:
        return {"status": "error", "message": error}
    cliente = shutil.which("mysql") or shutil.which("mariadb")
    r = _run([cliente, *args, "-e", f"CREATE DATABASE `{nuevo}`"], timeout=60, env=env)
    if r.returncode != 0:
        return {"status": "error", "message": _explicar(r.stderr)}
    return _restic_a_programa(ctx, snap, archivo, [cliente, *args, nuevo], env)


# ------------------------------------------------------------------------------------------------ PostgreSQL
def _pg_bin(nombre: str) -> str:
    exe = shutil.which(nombre)
    if exe:
        return exe
    for patron in ("C:\\Program Files\\PostgreSQL\\*\\bin\\" + nombre + ".exe", "/usr/lib/postgresql/*/bin/" + nombre):
        hallados = sorted(glob.glob(patron))
        if hallados:
            return hallados[-1]
    return ""


def _pg_base(cred: dict) -> tuple[list[str], list[str], dict, str]:
    """(prefijo para ejecutar como el usuario postgres, args de conexión, env, error)."""
    env = dict(os.environ)
    c = cred.get("postgresql") or {}
    args = []
    if c.get("host") or os.environ.get("OCTOPUS_PG_HOST"):
        args += ["-h", c.get("host") or os.environ["OCTOPUS_PG_HOST"]]
    if c.get("port"):
        args += ["-p", str(c["port"])]
    prefijo = []
    if c.get("usuario"):
        args += ["-U", c["usuario"]]
        env["PGPASSWORD"] = str(c.get("clave", ""))
    elif SYSTEM != "windows":
        es_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if es_root and shutil.which("runuser"):
            prefijo = ["runuser", "-u", "postgres", "--"]      # entra como el usuario «postgres» del sistema
        else:
            args += ["-U", "postgres"]
    psql = _pg_bin("psql")
    if not psql:
        return [], [], env, "No está el programa psql en este equipo"
    r = _run([*prefijo, psql, *args, "-d", "postgres", "-tAc", "SELECT 1"], timeout=30, env=env)
    if r.returncode != 0:
        return [], [], env, _explicar(r.stderr)
    return prefijo, args, env, ""


def _pg_detectar(cred: dict) -> dict:
    if not (_pg_bin("pg_dump") and _pg_bin("psql")):
        return {}
    pre, args, env, error = _pg_base(cred)
    if error:
        # pg_dump suelto (solo el cliente) sin servidor en el equipo: no es una base de datos de este equipo
        if "no responde" in error and not (cred.get("postgresql") or {}).get("host"):
            return {}
        return {"motor": "postgresql", "acceso": "sin_permiso", "mensaje": error, "bases": []}
    r = _run([*pre, _pg_bin("psql"), *args, "-d", "postgres", "-tAF", "\t", "-c",
              "SELECT datname, pg_database_size(datname) FROM pg_database WHERE datallowconn"], timeout=120, env=env)
    bases = []
    for linea in (r.stdout or "").splitlines():
        p = linea.split("\t")
        if len(p) == 2 and p[0] not in SISTEMA_PG:
            bases.append({"motor": "postgresql", "instancia": "local", "nombre": p[0], "tamano": int(p[1] or 0)})
    return {"motor": "postgresql", "acceso": "ok", "mensaje": "", "bases": bases}


def _pg_copiar(ctx: dict, bd: dict) -> dict:
    pre, args, env, error = _pg_base(ctx.get("cred", {}))
    if error:
        return {"status": "error", "message": error}
    return _a_restic_tuberia(ctx, bd, [*pre, _pg_bin("pg_dump"), *args, "-Fc", "-d", bd["nombre"]], env,
                             f"postgresql-{etiqueta(bd['nombre'])}.dump")


def _pg_restaurar(ctx: dict, snap: str, bd: dict, archivo: str, nuevo: str) -> dict:
    pre, args, env, error = _pg_base(ctx.get("cred", {}))
    if error:
        return {"status": "error", "message": error}
    r = _run([*pre, _pg_bin("psql"), *args, "-d", "postgres", "-c", f'CREATE DATABASE "{nuevo}"'], timeout=60, env=env)
    if r.returncode != 0:
        return {"status": "error", "message": _explicar(r.stderr)}
    return _restic_a_programa(ctx, snap, archivo, [*pre, _pg_bin("pg_restore"), *args, "--no-owner", "-d", nuevo], env)


# ------------------------------------------------------------------------------------------------ SQL Server
def _sql_instancias() -> list[str]:
    if os.environ.get("OCTOPUS_SQLSERVER_INSTANCIAS"):
        return [i for i in os.environ["OCTOPUS_SQLSERVER_INSTANCIAS"].split(";") if i.strip()]
    if SYSTEM != "windows":
        return []
    r = _run(["reg", "query", r"HKLM\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL"], timeout=30)
    nombres = [l.split()[0] for l in (r.stdout or "").splitlines() if "REG_SZ" in l]
    return ["." if n.upper() == "MSSQLSERVER" else f".\\{n}" for n in nombres]


def _sql_conexion(instancia: str, cred: dict) -> str:
    c = cred.get("sqlserver") or {}
    if c.get("usuario"):
        return f"Server={instancia};User ID={c['usuario']};Password={c.get('clave', '')};TrustServerCertificate=True"
    return f"Server={instancia};Integrated Security=True;TrustServerCertificate=True"


_PS_SQL = r"""
$ErrorActionPreference = 'Stop'
$cn = New-Object System.Data.SqlClient.SqlConnection $env:OCTOPUS_SQL_CONEXION
$cn.Open()
$cmd = $cn.CreateCommand(); $cmd.CommandText = $env:OCTOPUS_SQL; $cmd.CommandTimeout = 0
$t = New-Object System.Data.DataTable; $t.Load($cmd.ExecuteReader())
# la coma delante hace que cada fila salga como UNA fila (si no, PowerShell junta todas las columnas en una lista)
$filas = @($t | ForEach-Object { $f = $_; , @($t.Columns | ForEach-Object { [string]$f[$_.ColumnName] }) })
$cn.Close()
ConvertTo-Json -InputObject @($filas) -Depth 3 -Compress
"""


def _sql(instancia: str, cred: dict, consulta: str, timeout=3600) -> tuple[list, str]:
    """Ejecuta T-SQL con .NET (System.Data.SqlClient, viene con Windows). Devuelve (filas, error)."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return [], "No está PowerShell"
    env = dict(os.environ, OCTOPUS_SQL_CONEXION=_sql_conexion(instancia, cred), OCTOPUS_SQL=consulta)
    r = _run([exe, "-NoProfile", "-NonInteractive", "-Command", _PS_SQL], timeout=timeout, env=env)
    if r.returncode != 0:
        return [], _explicar(r.stderr or r.stdout)
    try:
        filas = json.loads(r.stdout or "[]")
    except ValueError:
        return [], (r.stdout or "")[-300:]
    filas = [f if isinstance(f, list) else [f] for f in (filas or [])]
    return filas, ""


def _sql_detectar(cred: dict) -> list[dict]:
    salida = []
    for inst in _sql_instancias():
        filas, error = _sql(inst, cred, "SELECT d.name, CAST(SUM(CAST(f.size AS bigint))*8192 AS bigint) FROM sys.databases d "
                                        "JOIN sys.master_files f ON f.database_id=d.database_id "
                                        "WHERE d.database_id>4 AND d.state=0 GROUP BY d.name", timeout=120)
        if error:
            salida.append({"motor": "sqlserver", "instancia": inst, "acceso": "sin_permiso", "mensaje": error, "bases": []})
            continue
        bases = [{"motor": "sqlserver", "instancia": inst, "nombre": f[0], "tamano": int(f[1] or 0)} for f in filas if f]
        salida.append({"motor": "sqlserver", "instancia": inst, "acceso": "ok", "mensaje": "", "bases": bases})
    return salida


def _sql_carpeta_copias(inst: str, cred: dict) -> tuple[str, str]:
    filas, error = _sql(inst, cred, "SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(4000)), "
                                    "CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(4000))", timeout=60)
    if error or not filas:
        return "", ""
    import tempfile
    copias_dir = (filas[0][0] or "").rstrip("\\") or tempfile.gettempdir()      # LocalDB no la dice: temporal
    datos_dir = (filas[0][1] or "").rstrip("\\") if len(filas[0]) > 1 else ""
    return copias_dir, datos_dir


def _sql_copiar(ctx: dict, bd: dict) -> dict:
    cred, inst, nombre = ctx.get("cred", {}), bd["instancia"], bd["nombre"]
    if not _id_valido(nombre):
        return {"status": "error", "message": "Nombre de base de datos no válido"}
    carpeta, _datos = _sql_carpeta_copias(inst, cred)
    if not carpeta:
        return {"status": "error", "message": "No encuentro la carpeta de copias de SQL Server"}
    bak = f"{carpeta}\\octopus_{_archivo_seguro(nombre)}.bak"      # nombre fijo: la retención agrupa bien
    _f, error = _sql(inst, cred, f"BACKUP DATABASE [{nombre}] TO DISK = N'{bak}' WITH COPY_ONLY, INIT, CHECKSUM")
    if error:
        return {"status": "error", "message": error}
    try:
        r = _run([ctx["bin"], "backup", bak, *_tags(bd), "--host", ctx["host"], "--json", *ctx.get("opts", [])],
                 timeout=12 * 3600, env=ctx["env"])
    finally:
        try:
            os.remove(bak)
        except OSError:
            pass
    if r.returncode not in (0, 3):
        return {"status": "error", "message": (r.stderr or r.stdout).strip()[-400:]}
    return {"status": "success", "snapshot_id": _resumen(r.stdout)}


def _sql_restaurar(ctx: dict, snap: str, bd: dict, archivo: str, nuevo: str) -> dict:
    cred, inst = ctx.get("cred", {}), bd["instancia"]
    carpeta, datos = _sql_carpeta_copias(inst, cred)
    if not carpeta:
        return {"status": "error", "message": "No encuentro la carpeta de copias de SQL Server"}
    bak = f"{carpeta}\\{nuevo}.bak"
    with open(bak, "wb") as fh:
        r = subprocess.run([ctx["bin"], "dump", snap, archivo], stdout=fh, stderr=subprocess.PIPE, env=ctx["env"],
                           timeout=12 * 3600)
    try:
        if r.returncode != 0:
            return {"status": "error", "message": r.stderr.decode(errors="replace")[-400:]}
        filas, error = _sql(inst, cred, f"RESTORE FILELISTONLY FROM DISK = N'{bak}'", timeout=600)
        if error:
            return {"status": "error", "message": error}
        destino = datos or carpeta
        moves = ", ".join(f"MOVE N'{f[0]}' TO N'{destino}\\{nuevo}_{i}{'.ldf' if (len(f) > 2 and f[2] == 'L') else '.mdf'}'"
                          for i, f in enumerate(filas))
        _f, error = _sql(inst, cred, f"RESTORE DATABASE [{nuevo}] FROM DISK = N'{bak}' WITH {moves}, RECOVERY")
        if error:
            return {"status": "error", "message": error}
        return {"status": "success"}
    finally:
        try:
            os.remove(bak)
        except OSError:
            pass


# ------------------------------------------------------------------------------------------------ común
def _restic_a_programa(ctx: dict, snap: str, archivo: str, programa: list[str], env_prog: dict) -> dict:
    """Saca un archivo de una copia y se lo pasa por tubería a un programa (mysql, pg_restore)."""
    try:
        d = subprocess.Popen([ctx["bin"], "dump", snap, archivo], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=ctx["env"])
    except OSError as exc:
        return {"status": "error", "message": str(exc)}
    try:
        r = subprocess.run(programa, stdin=d.stdout, capture_output=True, text=True, timeout=12 * 3600, env=env_prog)
    finally:
        d.stdout.close()
        rc = d.wait()
        err_d = (d.stderr.read() or b"").decode(errors="replace")
    if rc != 0:
        return {"status": "error", "message": "No se pudo leer la copia: " + err_d[-300:]}
    if r.returncode != 0:
        return {"status": "error", "message": _explicar(r.stderr)}
    return {"status": "success"}


def detectar(cred: dict | None = None) -> list[dict]:
    """Motores de este equipo con sus bases de datos: [{motor, instancia, acceso, mensaje, bases: [...]}]."""
    cred = cred or {}
    salida = []
    for d in (_mysql_detectar(cred), _pg_detectar(cred)):
        if d:
            salida.append(d)
    salida += _sql_detectar(cred)
    return salida


def copiar(ctx: dict, bd: dict) -> dict:
    """Copia de UNA base de datos. ctx = {bin, env, host, opts, cred}."""
    fn = {"mysql": _mysql_copiar, "postgresql": _pg_copiar, "sqlserver": _sql_copiar}.get(bd.get("motor"))
    if not fn or not _id_valido(bd.get("nombre", "")):
        return {"status": "error", "message": "Base de datos no válida"}
    res = fn(ctx, bd)
    res.update(motor=bd["motor"], nombre=bd["nombre"], instancia=bd.get("instancia", ""))
    return res


def copias(ctx: dict) -> list[dict]:
    """Copias de bases de datos de este equipo que hay en el almacén (la más nueva primero)."""
    r = _run([ctx["bin"], "snapshots", "--json", "--host", ctx["host"], "--tag", "bd"], timeout=300, env=ctx["env"])
    try:
        snaps = json.loads(r.stdout or "[]") or []
    except ValueError:
        snaps = []
    out = []
    for s in snaps:
        tags = s.get("tags") or []
        clave = next((t for t in tags if t.startswith("bd:")), "")
        partes = clave.split(":", 3)
        out.append({"id": s.get("short_id") or s.get("id", "")[:8], "time": s.get("time"),
                    "motor": partes[1] if len(partes) > 1 else "", "instancia": partes[2] if len(partes) > 2 else "",
                    "nombre": partes[3] if len(partes) > 3 else "", "rutas": s.get("paths") or []})
    out.sort(key=lambda c: c.get("time") or "", reverse=True)
    return out


def _archivo_de(ctx: dict, snap: str) -> str:
    """El único archivo que hay dentro de una copia de base de datos (el volcado o el .bak)."""
    r = _run([ctx["bin"], "ls", "--json", snap], timeout=300, env=ctx["env"])
    for linea in (r.stdout or "").splitlines():
        try:
            n = json.loads(linea)
        except ValueError:
            continue
        if n.get("struct_type") == "node" and n.get("type") == "file":
            return n.get("path", "")
    return ""


def restaurar(ctx: dict, snapshot: str, motor: str, nombre: str, instancia: str = "local") -> dict:
    """Recupera una copia como base de datos NUEVA, al lado de la original (que no se toca)."""
    if not re.fullmatch(r"[0-9a-fA-F]{6,64}", str(snapshot or "")):
        return {"status": "error", "message": "Copia no válida"}
    fn = {"mysql": _mysql_restaurar, "postgresql": _pg_restaurar, "sqlserver": _sql_restaurar}.get(motor)
    if not fn:
        return {"status": "error", "message": "Motor no soportado"}
    archivo = _archivo_de(ctx, snapshot)
    if not archivo:
        return {"status": "error", "message": "Esa copia está vacía o no es de una base de datos"}
    nuevo = nombre_recuperada(nombre)
    res = fn(ctx, snapshot, {"motor": motor, "nombre": nombre, "instancia": instancia}, archivo, nuevo)
    if res.get("status") == "success":
        res.update(base_nueva=nuevo, instrucciones=(
            f"La copia está ahora en la base de datos «{nuevo}», al lado de la original «{nombre}», que no se ha tocado. "
            f"Para usarla, cambia en tu programa la base de datos a «{nuevo}» o pide a tu informático que la renombre."))
    return res
