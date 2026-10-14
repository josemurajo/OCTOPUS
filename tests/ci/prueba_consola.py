#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""OCTOPUS - (pruebas de GitHub) modo consola «buscar-equipos»: recorre las ventanas como un usuario (con Textual pilot),
con la busqueda y la instalacion simuladas: redes, grupos, contrasenas por grupo, resumen final y registro."""
import asyncio, os, sqlite3, sys, tempfile, time
from pathlib import Path
P = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, P + "/lib")
import consola, descubrir, alta_grupo
from textual.widgets import SelectionList, Input, Button, DataTable, Static

d = tempfile.mkdtemp(); db = os.path.join(d, "t.db")
c = sqlite3.connect(db)
c.execute("create table systems (id integer primary key, hostname text, ip_address text, os_family text, status text, notes text)")
c.execute("create table audit_logs (id integer primary key, user_id, action, details, ip_address, timestamp, hash_anterior, hash)")
c.execute("insert into systems (hostname, ip_address, os_family, status, notes) values ('viejo','10.0.0.9','linux','ok','{\"grupo\":\"Casa\"}')")
c.commit(); c.close()
consola.entorno = lambda: ({"OCTOPUS_IP": "10.0.0.1"}, db)
descubrir.redes_propuestas = lambda env: ["10.0.0.0/24"]
EST = {"total": 4, "hechos": 0, "estado": "en_curso", "encontrados": [
    {"ip": "10.0.0.5", "nombre": "pc-linux", "so": "linux", "sistema": "Linux", "puertos": [22], "ssh": True, "ya_tiene": ""},
    {"ip": "10.0.0.6", "nombre": "pc-win", "so": "windows", "sistema": "Windows", "puertos": [445], "ssh": False, "ya_tiene": ""},
    {"ip": "10.0.0.7", "nombre": "pc-mala", "so": "linux", "sistema": "Linux", "puertos": [22], "ssh": True, "ya_tiene": ""},
    {"ip": "10.0.0.9", "nombre": "viejo", "so": "linux", "sistema": "Linux", "puertos": [22], "ssh": True, "ya_tiene": "viejo"}]}
pedidas = {}
def empezar(redes, conocidos, propias):
    pedidas.update(redes=redes, conocidos=conocidos, propias=propias); return "e1"
def ver(eid):
    EST["hechos"] = min(4, EST["hechos"] + 2)
    if EST["hechos"] == 4: EST["estado"] = "hecho"
    return dict(EST)
descubrir.empezar, descubrir.ver = empezar, ver
vistos = []
def instalar(db_, sid, q, u, p, solo, paso=lambda t: None, user_id=None):
    vistos.append((q["nombre"], u, p, solo)); paso("Copiando..."); time.sleep(0.3)
    return (q["nombre"] != "pc-mala", "Instalado y conectado." if q["nombre"] != "pc-mala" else "Usuario o contraseña incorrectos.")
alta_grupo.instalar = instalar

F = []
def chk(c, n, x=""):
    print(("PASS" if c else "FAIL"), n, x); c or F.append(n)

async def main():
    app = consola.app_ventanas()
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause()
        app.screen.query_one("#empezar", Button).press(); await pilot.pause()
        s = app.screen
        chk(list(s.query_one("#redes", SelectionList).selected) == ["10.0.0.0/24"], "red propuesta marcada")
        s.query_one("#otras", Input).value = "esto no es red"
        app.screen.query_one("#buscar", Button).press(); await pilot.pause()
        chk("esto no es red" in str(s.query_one("#error", Static).render()), "red mal escrita: avisa y no sigue")
        s.query_one("#otras", Input).value = "10.0.1.0/24"
        app.screen.query_one("#buscar", Button).press(); await pilot.pause(2.5)
        chk(pedidas.get("redes") == ["10.0.0.0/24", "10.0.1.0/24"], "busca en las dos redes", pedidas.get("redes"))
        chk("10.0.0.1" in pedidas.get("propias", ()), "no se busca a si mismo")
        s = app.screen
        chk(type(s).__name__ == "Resultados", "pasa a resultados", type(s).__name__)
        lista = s.query_one("#equipos", SelectionList)
        lista.select("10.0.0.9")
        
        chk(s.query_one("#seguir", Button).disabled, "Seguir desactivado sin grupos")
        lista.select("10.0.0.5"); lista.select("10.0.0.7")
        s.query_one("#grupo", Input).value = "Oficina"
        app.screen.query_one("#agrupar", Button).press(); await pilot.pause()
        lista.select("10.0.0.6"); s.query_one("#grupo", Input).value = "Almacen"
        app.screen.query_one("#agrupar", Button).press(); await pilot.pause()
        chk(all(q["ip"]!="10.0.0.9" for v in s.grupos.values() for q in v), "ya protegido nunca entra en un grupo"); chk(set(s.grupos) == {"Oficina", "Almacen"} and len(s.grupos["Oficina"]) == 2, "grupos hechos", {g: len(v) for g, v in s.grupos.items()})
        app.screen.query_one("#seguir", Button).press(); await pilot.pause()
        s = app.screen
        s.query_one("#usuario_0", Input).value = "admin"; s.query_one("#password_0", Input).value = "secreta"
        s.query_one("#solo_0").value = True
        s.query_one("#usuario_1", Input).value = "adm"; s.query_one("#password_1", Input).value = "x"
        app.screen.query_one("#instalar", Button).press(); await pilot.pause()
        for _ in range(40):
            await pilot.pause(0.2)
            if not app.screen.query_one("#terminar", Button).disabled: break
        s = app.screen
        fin = str(s.query_one("#final", Static).render())
        chk("1 equipo protegido" in fin and "1 no se pudo" in fin and "1 dado de alta sin instalar" in fin and "OpenSSH" in fin, "resumen final", fin.splitlines()[0])
        chk("pc-mala" in fin and "incorrectos" in fin, "dice por qué falló")
        chk("https://10.0.0.1:8080" in fin, "da la dirección del panel")
        chk(("pc-linux", "admin", "secreta", True) in vistos, "usa usuario/contraseña del grupo y solo-clave")
        chk(not any(v[0] == "pc-win" for v in vistos), "sin SSH no intenta instalar")
        t = s.query_one("#tabla", DataTable)
        chk(t.row_count == 3, "una fila por equipo", t.row_count)
        chk(s.credenciales == {}, "olvida las contraseñas al terminar")
        app.screen.query_one("#terminar", Button).press(); await pilot.pause()
    chk(app.return_value and "1 equipo protegido" in app.return_value, "sale con el resumen", app.return_value)
    c = sqlite3.connect(db)
    chk(c.execute("select count(*) from systems").fetchone()[0] == 4, "3 equipos dados de alta")
    acc = [r[0] for r in c.execute("select action from audit_logs")]
    chk(acc.count("SYSTEM_ADD") == 3, "queda en el registro", acc)
    chk(not any("secreta" in (r[0] or "") for r in c.execute("select details from audit_logs")), "contraseña nunca en el registro")
asyncio.run(main())
print("FALLOS:", F or "ninguno")
sys.exit(1 if F else 0)
