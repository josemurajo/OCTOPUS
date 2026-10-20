# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Copias de bases de datos (agentes/octopus_bd.py) con MySQL/MariaDB y PostgreSQL DE VERDAD y restic DE VERDAD.

Crea una «tienda» en MySQL y una «contabilidad» en PostgreSQL, las copia, estropea las originales, recupera las copias
como bases NUEVAS y comprueba que tienen los datos de antes y que las originales no se han tocado.
Necesita: restic, un MySQL/MariaDB y un PostgreSQL a los que se pueda entrar. Variables opcionales:
  PRUEBA_MYSQL_USUARIO / PRUEBA_MYSQL_CLAVE / OCTOPUS_MYSQL_SOCKET    (por defecto root por el socket)
  PRUEBA_PG_USUARIO / PRUEBA_PG_CLAVE / OCTOPUS_PG_HOST              (por defecto el usuario del sistema postgres)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent.parent / "agentes"))
import octopus_bd as bd  # noqa: E402

F = []


def chk(c, n, x=""):
    print("OK  " if c else "MAL ", n, x)
    c or F.append(n)


cred = {}
if os.environ.get("PRUEBA_MYSQL_USUARIO"):
    cred["mysql"] = {"usuario": os.environ["PRUEBA_MYSQL_USUARIO"], "clave": os.environ.get("PRUEBA_MYSQL_CLAVE", "")}
if os.environ.get("PRUEBA_PG_USUARIO"):
    cred["postgresql"] = {"usuario": os.environ["PRUEBA_PG_USUARIO"], "clave": os.environ.get("PRUEBA_PG_CLAVE", "")}

args_my, env_my, err_my = bd._mysql_base(cred)
pre_pg, args_pg, env_pg, err_pg = bd._pg_base(cred)
if err_my or err_pg:
    print("No se puede entrar en las bases de datos de prueba:", err_my, err_pg)
    sys.exit(1)
MYSQL = shutil.which("mysql") or shutil.which("mariadb")
PSQL = bd._pg_bin("psql")


def my(sql, base=""):
    r = subprocess.run([MYSQL, *args_my, "-NBe", sql, *([base] if base else [])], capture_output=True, text=True, env=env_my)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout.strip()


def pg(sql, base="postgres"):
    r = subprocess.run([*pre_pg, PSQL, *args_pg, "-d", base, "-tAc", sql], capture_output=True, text=True, env=env_pg)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout.strip()


# ---------------------------------------------------------------- datos de prueba
my("DROP DATABASE IF EXISTS tienda_prueba")
my("CREATE DATABASE tienda_prueba")
my("CREATE TABLE clientes (id INT PRIMARY KEY, nombre VARCHAR(80), saldo DECIMAL(10,2))", "tienda_prueba")
my("INSERT INTO clientes VALUES " + ",".join(f"({i},'Cliente ñ {i}',{i * 1.5})" for i in range(1, 501)), "tienda_prueba")
my("CREATE TRIGGER no_negativo BEFORE UPDATE ON clientes FOR EACH ROW SET NEW.saldo = GREATEST(NEW.saldo, 0)", "tienda_prueba")
for b in pg("SELECT datname FROM pg_database WHERE datname LIKE 'contabilidad_prueba%'").split():
    pg(f'DROP DATABASE "{b}"')
pg("CREATE DATABASE contabilidad_prueba")
pg("CREATE TABLE asientos (id serial PRIMARY KEY, concepto text, importe numeric)", "contabilidad_prueba")
pg("INSERT INTO asientos (concepto, importe) SELECT 'Factura ' || g, g * 10 FROM generate_series(1, 800) g", "contabilidad_prueba")

T = Path(tempfile.mkdtemp(prefix="octopus_bd_"))
restic = shutil.which("restic")
env = {**os.environ, "RESTIC_REPOSITORY": str(T / "almacen"), "RESTIC_PASSWORD": "prueba-bd", "RESTIC_CACHE_DIR": str(T / "cache")}
subprocess.run([restic, "init"], env=env, check=True, capture_output=True)
ctx = {"bin": restic, "env": env, "host": "servidor-bd", "opts": [], "cred": cred}

# ---------------------------------------------------------------- detectar
motores = {m["motor"]: m for m in bd.detectar(cred)}
chk(motores.get("mysql", {}).get("acceso") == "ok" and motores.get("postgresql", {}).get("acceso") == "ok", "entra en MySQL y PostgreSQL")
my_bases = {b["nombre"]: b for b in motores["mysql"]["bases"]}
pg_bases = {b["nombre"]: b for b in motores["postgresql"]["bases"]}
chk("tienda_prueba" in my_bases and "mysql" not in my_bases and "information_schema" not in my_bases, "MySQL: ve la tienda, no las de sistema")
chk("contabilidad_prueba" in pg_bases and "template0" not in pg_bases, "PostgreSQL: ve la contabilidad, no las de sistema")
chk(pg_bases["contabilidad_prueba"]["tamano"] > 0, "con su tamaño")

# ---------------------------------------------------------------- copiar
r1 = bd.copiar(ctx, my_bases["tienda_prueba"])
r2 = bd.copiar(ctx, pg_bases["contabilidad_prueba"])
chk(r1["status"] == "success" and r1.get("snapshot_id"), "MySQL: copiada directo al almacén", r1.get("message", ""))
chk(r2["status"] == "success" and r2.get("snapshot_id"), "PostgreSQL: copiada directo al almacén", r2.get("message", ""))
antes = len(bd.copias(ctx))
rx = bd.copiar(ctx, {"motor": "mysql", "instancia": "local", "nombre": "no_existe_esta_bd"})
chk(rx["status"] == "error" and len(bd.copias(ctx)) == antes, "si el volcado falla: error y no queda una copia a medias")
chk(bd.copiar(ctx, {"motor": "mysql", "nombre": "x'; DROP DATABASE tienda_prueba; --"})["status"] == "error"
    and bd.copiar(ctx, {"motor": "postgresql", "nombre": "--help"})["status"] == "error", "nombres con trampa: rechazados")
cs = bd.copias(ctx)
chk(len(cs) == 2 and {(c["motor"], c["nombre"]) for c in cs} == {("mysql", "tienda_prueba"), ("postgresql", "contabilidad_prueba")},
    "lista de copias con motor y nombre", cs)

# ---------------------------------------------------------------- «desastre» y recuperar
my("DELETE FROM clientes WHERE id > 10", "tienda_prueba")
pg("DELETE FROM asientos WHERE id > 5", "contabilidad_prueba")
rr1 = bd.restaurar(ctx, r1["snapshot_id"][:8], "mysql", "tienda_prueba")
chk(rr1["status"] == "success" and rr1.get("base_nueva", "").startswith("tienda_prueba_recuperada_"), "MySQL: recuperada como base nueva",
    rr1.get("message", ""))
if rr1["status"] == "success":
    n = rr1["base_nueva"]
    chk(my("SELECT COUNT(*), SUM(saldo) FROM clientes", n) == "500\t187875.00", "MySQL: la recuperada tiene los 500 clientes y los saldos", my("SELECT COUNT(*), SUM(saldo) FROM clientes", n))
    chk(my("SELECT nombre FROM clientes WHERE id=7", n) == "Cliente ñ 7", "con las tildes y eñes bien")
    chk(my(f"SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema='{n}'") == "1", "y el disparador (trigger)")
    chk(my("SELECT COUNT(*) FROM clientes", "tienda_prueba") == "10", "MySQL: la original no se toca")
    chk("cambia en tu programa" in rr1.get("instrucciones", ""), "explica cómo usarla")
    my(f"DROP DATABASE `{n}`")
rr2 = bd.restaurar(ctx, r2["snapshot_id"][:8], "postgresql", "contabilidad_prueba")
chk(rr2["status"] == "success", "PostgreSQL: recuperada como base nueva", rr2.get("message", ""))
if rr2["status"] == "success":
    n = rr2["base_nueva"]
    chk(pg("SELECT COUNT(*), SUM(importe) FROM asientos", n) == "800|3204000", "PostgreSQL: la recuperada tiene los 800 asientos", pg("SELECT COUNT(*), SUM(importe) FROM asientos", n))
    chk(pg("SELECT COUNT(*) FROM asientos", "contabilidad_prueba") == "5", "PostgreSQL: la original no se toca")
    pg(f'DROP DATABASE "{n}"')
chk(bd.restaurar(ctx, "zzz; rm -rf /", "mysql", "tienda_prueba")["status"] == "error", "copia con nombre raro: rechazada")

# ---------------------------------------------------------------- mensajes que se entienden
chk("permiso" in bd._explicar("ERROR 1045 (28000): Access denied for user 'x'@'localhost'"), "sin permiso: lo dice claro")
chk("no responde" in bd._explicar("Can't connect to local MySQL server through socket"), "motor parado: lo dice claro")
chk(bd.nombre_recuperada("Contabilidad 2026!").startswith("Contabilidad_2026__recuperada_"), "nombre de la recuperada válido")

my("DROP DATABASE IF EXISTS tienda_prueba")
pg('DROP DATABASE IF EXISTS "contabilidad_prueba"')
shutil.rmtree(T, ignore_errors=True)
print("FALLOS:", F or "ninguno")
sys.exit(1 if F else 0)
