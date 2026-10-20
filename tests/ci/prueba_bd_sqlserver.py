# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Copias de SQL Server (agentes/octopus_bd.py) en Windows con SQL Server LocalDB DE VERDAD y restic DE VERDAD.

Crea una base de datos, la copia (BACKUP ... COPY_ONLY), la estropea, la recupera como base NUEVA (RESTORE ... MOVE) y
comprueba los datos. Si el equipo no tiene LocalDB, la prueba se OMITE (y lo dice bien claro).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if os.name != "nt":
    print("OMITIDA: solo en Windows")
    sys.exit(0)
loc = shutil.which("SqlLocalDB") or next((str(p) for p in Path("C:/Program Files/Microsoft SQL Server").glob("*/Tools/Binn/SqlLocalDB.exe")), "")
if not loc:
    print("OMITIDA: este equipo no tiene SQL Server LocalDB")
    sys.exit(0)
subprocess.run([loc, "create", "MSSQLLocalDB"], capture_output=True)
r = subprocess.run([loc, "start", "MSSQLLocalDB"], capture_output=True, text=True)
print("LocalDB:", (r.stdout or r.stderr).strip()[:200])
INST = r"(localdb)\MSSQLLocalDB"
os.environ["OCTOPUS_SQLSERVER_INSTANCIAS"] = INST

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "agentes"))
import octopus_bd as bd  # noqa: E402

F = []


def chk(c, n, x=""):
    print("OK  " if c else "MAL ", n, x)
    c or F.append(n)


def q(sql):
    filas, err = bd._sql(INST, {}, sql, timeout=600)
    if err:
        raise RuntimeError(err)
    return filas


carpeta = Path(tempfile.mkdtemp(prefix="octopus_sql_"))
for f in q("SELECT name FROM sys.databases WHERE name LIKE 'tienda_sql%'"):
    q(f"ALTER DATABASE [{f[0]}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{f[0]}]")
q(f"CREATE DATABASE tienda_sql ON (NAME = tienda_sql, FILENAME = '{carpeta}\\tienda_sql.mdf') "
  f"LOG ON (NAME = tienda_sql_log, FILENAME = '{carpeta}\\tienda_sql_log.ldf')")
q("CREATE TABLE tienda_sql.dbo.pedidos (id INT PRIMARY KEY, cliente NVARCHAR(60), total DECIMAL(10,2))")
q("INSERT INTO tienda_sql.dbo.pedidos SELECT TOP 250 ROW_NUMBER() OVER (ORDER BY (SELECT 1)), N'Señora ' + "
  "CAST(ROW_NUMBER() OVER (ORDER BY (SELECT 1)) AS nvarchar), 10 FROM sys.all_objects")

restic = shutil.which("restic")
T = Path(tempfile.mkdtemp(prefix="octopus_sqlr_"))
env = {**os.environ, "RESTIC_REPOSITORY": str(T / "almacen"), "RESTIC_PASSWORD": "prueba-sql", "RESTIC_CACHE_DIR": str(T / "cache")}
subprocess.run([restic, "init"], env=env, check=True, capture_output=True)
ctx = {"bin": restic, "env": env, "host": "windows-sql", "opts": [], "cred": {}}

motores = bd.detectar({})
sqlm = [m for m in motores if m["motor"] == "sqlserver"]
chk(sqlm and sqlm[0]["acceso"] == "ok", "entra en SQL Server (cuenta de Windows)", sqlm[0].get("mensaje", "") if sqlm else motores)
bases = {b["nombre"]: b for m in sqlm for b in m.get("bases", [])}
chk("tienda_sql" in bases and "master" not in bases, "ve la base de datos, no las de sistema", list(bases))
r1 = bd.copiar(ctx, bases.get("tienda_sql", {"motor": "sqlserver", "instancia": INST, "nombre": "tienda_sql"}))
chk(r1["status"] == "success" and r1.get("snapshot_id"), "copiada (BACKUP COPY_ONLY) al almacén", r1.get("message", ""))
cs = bd.copias(ctx)
chk(len(cs) == 1 and cs[0]["motor"] == "sqlserver" and cs[0]["nombre"] == "tienda_sql", "aparece en las copias", cs)
q("DELETE FROM tienda_sql.dbo.pedidos WHERE id > 5")
if r1["status"] == "success":
    rr = bd.restaurar(ctx, r1["snapshot_id"][:8], "sqlserver", "tienda_sql", INST)
    chk(rr["status"] == "success", "recuperada como base nueva (RESTORE con MOVE)", rr.get("message", ""))
    if rr["status"] == "success":
        n = rr["base_nueva"]
        chk(q(f"SELECT COUNT(*), SUM(total) FROM [{n}].dbo.pedidos") == [["250", "2500.00"]], "la nueva tiene los 250 pedidos",
            q(f"SELECT COUNT(*), SUM(total) FROM [{n}].dbo.pedidos"))
        chk(q(f"SELECT cliente FROM [{n}].dbo.pedidos WHERE id = 7") == [["Señora 7"]], "con las eñes bien")
        chk(q("SELECT COUNT(*) FROM tienda_sql.dbo.pedidos") == [["5"]], "la original no se toca")
        q(f"ALTER DATABASE [{n}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{n}]")
q("ALTER DATABASE tienda_sql SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE tienda_sql")
print("FALLOS:", F or "ninguno")
sys.exit(1 if F else 0)
