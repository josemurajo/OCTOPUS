#!/usr/bin/env python3
"""
OCTOPUS - Modo consola: buscar los equipos de la red y protegerlos, con ventanas, colores y ratón.

Para servidores sin escritorio (o por SSH) y para quien empieza: nada de comandos, solo elegir y pulsar.
Usa exactamente las mismas funciones que el botón «Buscar equipos en la red» del panel (descubrir.py, alta_grupo.py).

    sudo bash octopus.sh buscar-equipos         (Linux y Mac)      octopus.ps1 buscar-equipos   (Windows)
    python lib/consola.py --sencillo           (sin ventanas: preguntas en texto, para consolas muy básicas)
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))

import alta_grupo   # noqa: E402
import descubrir    # noqa: E402

LOGO = r"""
   ___   ____ _____ ___  ____  _   _ ____
  / _ \ / ___|_   _/ _ \|  _ \| | | / ___|
 | | | | |     | || | | | |_) | | | \___ \
 | |_| | |___  | || |_| |  __/| |_| |___) |
  \___/ \____| |_| \___/|_|    \___/|____/
"""


# ----------------------------------------------------------------- lo comun a los dos modos
def entorno() -> tuple[dict, str]:
    import configuracion
    env = configuracion.leer_env()
    db = env.get("DB_PATH", "./data/admin_panel.db")
    db = db if os.path.isabs(db) else str((BASE_DIR / db).resolve())
    return env, db


def ips_propias(env: dict) -> set:
    return {x.strip() for x in [env.get("OCTOPUS_IP", "")] + env.get("OCTOPUS_NOMBRES_EXTRA", "").split(",") if x.strip()}


def direccion_panel(env: dict) -> str:
    host = env.get("OCTOPUS_PUBLIC_HOST") or env.get("OCTOPUS_IP") or "IP-del-servidor"
    return f"https://{host}:{env.get('ADMIN_PORT', '8080')}"


def resumen(filas: list[dict]) -> str:
    ok = sum(1 for f in filas if f["estado"] == "ok")
    mal = [f for f in filas if f["estado"] == "error"]
    pend = [f for f in filas if f["estado"] == "pendiente"]
    partes = [f"{ok} equipo{'s' if ok != 1 else ''} protegido{'s' if ok != 1 else ''}"]
    if mal:
        partes.append(f"{len(mal)} no se pudo")
    if pend:
        partes.append(f"{len(pend)} dado{'s' if len(pend) != 1 else ''} de alta sin instalar")
    nada = [f for f in filas if f["estado"] == "nada"]
    if nada:
        partes.append(f"{len(nada)} ya existía{'n' if len(nada) != 1 else ''} con ese nombre (no se ha tocado)")
    return ", ".join(partes)


def preparar(db: str, grupos: dict[str, list[dict]]) -> list[dict]:
    """Da de alta los equipos elegidos (igual que el panel). Devuelve una fila por equipo con lo que toca hacer."""
    filas = []
    for grupo, equipos in grupos.items():
        for q in equipos:
            sid = alta_grupo.alta(db, q, grupo, "modo consola")
            filas.append({"q": q, "grupo": grupo, "sid": sid,
                          "estado": "nada" if sid is None else "esperando",
                          "mensaje": "Ya existía un equipo con ese nombre: no se ha tocado." if sid is None else "En cola..."})
    return filas


def instalar_todos(db: str, filas: list[dict], credenciales: dict, aviso) -> None:
    """Instala a la vez en todos los que se pueda. aviso(fila) se llama cada vez que cambia una fila."""
    hilos = []
    for f in filas:
        if f["sid"] is None:
            continue
        usuario, password, solo_clave = credenciales.get(f["grupo"], ("", "", False))
        falta = alta_grupo.que_falta(f["q"], usuario, password)
        if falta:
            f.update(estado="pendiente", mensaje=falta)   # dado de alta; se instala luego desde su ficha
            aviso(f)
            continue

        def uno(f=f, usuario=usuario, password=password, solo_clave=solo_clave):
            def paso(texto):
                f.update(estado="en_curso", mensaje=texto)
                aviso(f)
            paso("Conectando...")
            ok, msg = alta_grupo.instalar(db, f["sid"], f["q"], usuario, password, solo_clave, paso=paso)
            f.update(estado="ok" if ok else "error", mensaje=msg)
            aviso(f)
        t = threading.Thread(target=uno, daemon=True)
        t.start()
        hilos.append(t)
    for t in hilos:
        t.join()


# ----------------------------------------------------------------- modo con ventanas (Textual)
def app_ventanas():
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import Screen
    from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input, Label, ProgressBar, SelectionList,
                                 Static)
    from textual.widgets.selection_list import Selection

    AYUDA = ("Ratón: pulsa en lo que quieras.  Teclado: Tab para moverte, Espacio para marcar, Intro para seguir, "
             "Esc para volver atrás, Q para salir.")

    class Paso(Screen):
        BINDINGS = [Binding("escape", "atras", "Atrás"), Binding("q", "app.quit", "Salir"),
                    Binding("f1", "ayuda", "Ayuda")]

        def action_atras(self):
            if len(self.app.screen_stack) > 2:
                self.app.pop_screen()

        def action_ayuda(self):
            self.app.notify(AYUDA, title="Cómo se maneja", timeout=10)

    class Bienvenida(Paso):
        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical(classes="centro"):
                yield Static(LOGO, classes="logo")
                yield Static("Te ayudo a proteger los equipos de tu red en 4 pasos, sin escribir comandos:\n"
                             "  1. Busco los equipos que hay en la red.\n  2. Eliges cuáles proteger y los pones en grupos.\n"
                             "  3. Escribes el usuario y la contraseña de cada grupo (se usan una vez y se olvidan).\n"
                             "  4. Instalo OCTOPUS en todos a la vez y te enseño cómo va cada uno.", classes="texto")
                with Horizontal(classes="botones"):
                    yield Button("Buscar equipos en la red", id="empezar", variant="primary")
                    yield Button("Salir", id="salir")
            yield Footer()

        @on(Button.Pressed, "#empezar")
        def empezar(self):
            self.app.push_screen(Redes())

        @on(Button.Pressed, "#salir")
        def salir(self):
            self.app.exit()

    class Redes(Paso):
        def compose(self) -> ComposeResult:
            env = self.app.env
            yield Header()
            with VerticalScroll(classes="centro"):
                yield Label("Paso 1 de 4 · ¿Qué redes busco?", classes="titulo")
                yield Static("Te propongo la red de este servidor. Marca o desmarca con Espacio o con el ratón.", classes="texto")
                propuestas = descubrir.redes_propuestas(env)
                yield SelectionList[str](*[Selection(r, r, True) for r in propuestas], id="redes")
                if not propuestas:
                    yield Static("No he podido saber la red de este servidor: escríbela abajo.", classes="aviso")
                yield Label("¿Otras redes? (por ejemplo 192.168.2.0/24 o 10.0.5.*, separadas por comas)")
                yield Input(placeholder="192.168.2.0/24", id="otras")
                yield Static("", id="error", classes="error")
                with Horizontal(classes="botones"):
                    yield Button("Buscar", id="buscar", variant="primary")
                    yield Button("Atrás", id="atras")
            yield Footer()

        @on(Button.Pressed, "#atras")
        def atras(self):
            self.action_atras()

        @on(Input.Submitted, "#otras")
        @on(Button.Pressed, "#buscar")
        def buscar(self):
            redes, errores = [], []
            texto = self.query_one("#otras", Input).value
            for r in list(self.query_one("#redes", SelectionList).selected) + texto.replace(";", ",").split(","):
                if not r.strip():
                    continue
                try:
                    red = descubrir.validar_red(r)
                    if red not in redes:
                        redes.append(red)
                except ValueError as exc:
                    errores.append(f"«{r.strip()}»: {exc}")
            if errores or not redes:
                self.query_one("#error", Static).update("\n".join(errores) or "Elige o escribe al menos una red.")
                return
            conocidos, _, _ = alta_grupo.conocidos(self.app.db)
            eid = descubrir.empezar(redes, conocidos, ips_propias(self.app.env))
            self.app.push_screen(Barrido(eid))

    class Barrido(Paso):
        def __init__(self, eid):
            super().__init__()
            self.eid = eid

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical(classes="centro"):
                yield Label("Paso 1 de 4 · Buscando equipos...", classes="titulo")
                yield Static("Solo pruebo si responden unos pocos puertos típicos: no entro en ningún equipo.", classes="texto")
                yield ProgressBar(id="barra", show_eta=False)
                yield Static("", id="cuenta")
            yield Footer()

        def on_mount(self):
            self.set_interval(0.5, self.mirar)

        def mirar(self):
            e = descubrir.ver(self.eid)
            if not e:
                return
            self.query_one("#barra", ProgressBar).update(total=max(1, e["total"]), progress=e["hechos"])
            self.query_one("#cuenta", Static).update(f"{e['hechos']} de {e['total']} direcciones · "
                                                     f"{len(e['encontrados'])} equipos encontrados")
            if e["estado"] == "hecho":
                self.app.switch_screen(Resultados(self.eid))

    class Resultados(Paso):
        def __init__(self, eid):
            super().__init__()
            self.eid = eid
            self.grupos: dict[str, list[dict]] = {}

        def compose(self) -> ComposeResult:
            e = descubrir.ver(self.eid)
            self.encontrados = {q["ip"]: q for q in e["encontrados"]}
            _, grupos_existentes, _ = alta_grupo.conocidos(self.app.db)
            yield Header()
            with VerticalScroll(classes="centro"):
                yield Label(f"Paso 2 de 4 · He encontrado {len(self.encontrados)} equipo"
                            f"{'s' if len(self.encontrados) != 1 else ''}", classes="titulo")
                yield Static("Marca los que quieras proteger, escribe un grupo (por ejemplo «Oficina») y pulsa "
                             "«Poner en este grupo». Repite con otros grupos si quieres. Los que ya están protegidos "
                             "no se pueden marcar.", classes="texto")
                opciones = []
                for q in self.encontrados.values():
                    etiqueta = f"{q['nombre']:<22} {q['ip']:<15} {q['sistema']:<22}"
                    if q.get("ya_tiene"):
                        etiqueta += f"  ✓ ya protegido ({q['ya_tiene']})"
                    elif not q.get("ssh"):
                        etiqueta += "  (sin SSH: se le dará de alta y te digo cómo instalarlo)"
                    opciones.append(Selection(etiqueta, q["ip"], False, disabled=bool(q.get("ya_tiene"))))
                yield SelectionList[str](*opciones, id="equipos")
                with Horizontal(classes="fila"):
                    yield Input(value=(grupos_existentes or ["Oficina"])[0], placeholder="Nombre del grupo", id="grupo")
                    yield Button("Poner en este grupo", id="agrupar", variant="primary")
                yield Static("Todavía no has puesto ningún equipo en un grupo.", id="grupos")
                with Horizontal(classes="botones"):
                    yield Button("Seguir", id="seguir", variant="success", disabled=True)
                    yield Button("Buscar otra vez", id="otra")
            yield Footer()

        @on(Button.Pressed, "#agrupar")
        @on(Input.Submitted, "#grupo")
        def agrupar(self):
            lista = self.query_one("#equipos", SelectionList)
            grupo = self.query_one("#grupo", Input).value.strip()[:40] or "Oficina"
            elegidos = [ip for ip in lista.selected if not self.encontrados[ip].get("ya_tiene")]
            if not elegidos:
                self.app.notify("Marca primero algún equipo (Espacio o ratón).", severity="warning")
                return
            for ip in elegidos:
                for g in self.grupos.values():
                    g[:] = [q for q in g if q["ip"] != ip]
                self.grupos.setdefault(grupo, []).append(self.encontrados[ip])
            self.grupos = {g: v for g, v in self.grupos.items() if v}
            lista.deselect_all()
            texto = "\n".join(f"[b]{g}[/b]: " + ", ".join(q["nombre"] for q in v) for g, v in self.grupos.items())
            self.query_one("#grupos", Static).update(texto)
            self.query_one("#seguir", Button).disabled = not self.grupos

        @on(Button.Pressed, "#otra")
        def otra(self):
            self.app.switch_screen(Redes())

        @on(Button.Pressed, "#seguir")
        def seguir(self):
            self.app.push_screen(Credenciales(self.grupos))

    class Credenciales(Paso):
        def __init__(self, grupos):
            super().__init__()
            self.grupos = grupos

        def compose(self) -> ComposeResult:
            yield Header()
            with VerticalScroll(classes="centro"):
                yield Label("Paso 3 de 4 · Usuario y contraseña de cada grupo", classes="titulo")
                yield Static("Un usuario administrador de esos equipos. Se usa una sola vez para instalar y no se guarda "
                             "en ningún sitio. Si lo dejas en blanco, los equipos se dan de alta y los instalas luego.",
                             classes="texto")
                for i, (g, equipos) in enumerate(self.grupos.items()):
                    yield Label(f"[b]{g}[/b] · " + ", ".join(q["nombre"] for q in equipos), classes="grupo")
                    with Horizontal(classes="fila"):
                        yield Input(placeholder="usuario", id=f"usuario_{i}")
                        yield Input(placeholder="contraseña", password=True, id=f"password_{i}")
                    if any(q["so"] == "linux" for q in equipos):
                        yield Checkbox("Después, que en los Linux solo se pueda entrar por SSH con la clave del servidor",
                                       id=f"solo_{i}")
                with Horizontal(classes="botones"):
                    yield Button("Instalar en todos", id="instalar", variant="primary")
                    yield Button("Atrás", id="atras")
            yield Footer()

        @on(Button.Pressed, "#atras")
        def atras(self):
            self.action_atras()

        @on(Button.Pressed, "#instalar")
        def instalar(self):
            cred = {}
            for i, g in enumerate(self.grupos):
                solo = self.query(f"#solo_{i}")
                cred[g] = (self.query_one(f"#usuario_{i}", Input).value.strip(),
                           self.query_one(f"#password_{i}", Input).value,
                           bool(solo) and solo.first(Checkbox).value)
                self.query_one(f"#password_{i}", Input).value = ""   # que no se quede en la pantalla
            self.app.push_screen(Instalando(self.grupos, cred))

    class Instalando(Paso):
        BINDINGS = [Binding("q", "app.quit", "Salir")]

        def __init__(self, grupos, credenciales):
            super().__init__()
            self.grupos, self.credenciales = grupos, credenciales

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical(classes="centro"):
                yield Label("Paso 4 de 4 · Instalando OCTOPUS en los equipos", classes="titulo")
                yield DataTable(id="tabla", zebra_stripes=True, cursor_type="row")
                yield Static("", id="final", classes="texto")
                with Horizontal(classes="botones"):
                    yield Button("Terminar", id="terminar", variant="success", disabled=True)
            yield Footer()

        def on_mount(self):
            t = self.query_one("#tabla", DataTable)
            t.add_columns("", "Equipo", "Grupo", "IP", "Cómo va")
            self.filas = preparar(self.app.db, self.grupos)
            for n, f in enumerate(self.filas):
                t.add_row(*self._celdas(f), key=str(n))
            self.trabajar()

        def _celdas(self, f):
            icono = {"ok": "[green]✓[/]", "error": "[red]✗[/]", "en_curso": "[yellow]…[/]", "esperando": "·",
                     "pendiente": "[yellow]![/]", "nada": "–"}.get(f["estado"], "·")
            return icono, f["q"]["nombre"], f["grupo"], f["q"]["ip"], f["mensaje"][:110]

        def _pintar(self, f):
            t = self.query_one("#tabla", DataTable)
            n = str(self.filas.index(f))
            for col, valor in zip(t.columns.keys(), self._celdas(f)):
                t.update_cell(n, col, valor)

        @work(thread=True)
        def trabajar(self):
            instalar_todos(self.app.db, self.filas, self.credenciales,
                           lambda f: self.app.call_from_thread(self._pintar, f))
            self.credenciales = {}
            self.app.call_from_thread(self._fin)

        def _fin(self):
            mal = [f for f in self.filas if f["estado"] == "error"]
            texto = f"[b]{resumen(self.filas)}[/b]."
            for f in mal:
                texto += f"\n[red]✗[/] {f['q']['nombre']}: {f['mensaje']}"
            for f in (f for f in self.filas if f["estado"] in ("pendiente", "nada")):
                texto += f"\n[yellow]![/] {f['q']['nombre']}: {f['mensaje']}"
            texto += f"\n\nPanel: {direccion_panel(self.app.env)}  (los equipos ya aparecen en «Equipos»)"
            self.query_one("#final", Static).update(texto)
            self.query_one("#terminar", Button).disabled = False

        @on(Button.Pressed, "#terminar")
        def terminar(self):
            self.app.exit(resumen(self.filas))

    class Consola(App):
        TITLE = "OCTOPUS"
        SUB_TITLE = "Buscar y proteger los equipos de la red"
        CSS = """
        Screen { background: $surface; }
        .centro { padding: 1 2; }
        .logo { color: $accent; text-style: bold; }
        .titulo { text-style: bold; color: $accent; margin: 0 0 1 0; }
        .texto { margin: 0 0 1 0; }
        .grupo { margin: 1 0 0 0; }
        .error { color: $error; }
        .aviso { color: $warning; }
        .botones { height: auto; margin: 1 0; }
        .botones Button { margin: 0 2 0 0; }
        .fila { height: auto; }
        .fila Input { width: 1fr; }
        SelectionList { height: auto; max-height: 20; }
        DataTable { height: 1fr; }
        """

        def __init__(self):
            super().__init__()
            self.env, self.db = entorno()

        def on_mount(self):
            self.push_screen(Bienvenida())

    return Consola()


# ----------------------------------------------------------------- modo sencillo (preguntas en texto)
def modo_sencillo() -> int:
    import getpass
    env, db = entorno()
    print(LOGO)
    print("OCTOPUS - buscar y proteger los equipos de la red (modo sencillo). Ctrl+C para salir.\n")
    propuestas = descubrir.redes_propuestas(env)
    texto = input(f"¿Qué redes busco? [{', '.join(propuestas) or 'escribe una, p. ej. 192.168.1.0/24'}]: ").strip()
    redes = []
    for r in (texto.replace(";", ",").split(",") if texto else propuestas):
        try:
            redes.append(descubrir.validar_red(r))
        except ValueError as exc:
            print(f"  «{r}»: {exc}")
    if not redes:
        print("No hay ninguna red válida.")
        return 1
    eid = descubrir.empezar(redes, alta_grupo.conocidos(db)[0], ips_propias(env))
    while (e := descubrir.ver(eid))["estado"] != "hecho":
        print(f"\r  Buscando... {e['hechos']}/{e['total']} ({len(e['encontrados'])} encontrados)", end="", flush=True)
        time.sleep(0.5)
    print()
    libres = [q for q in e["encontrados"] if not q.get("ya_tiene")]
    for q in e["encontrados"]:
        print(f"  {'[ya protegido] ' if q.get('ya_tiene') else ''}{q['nombre']:<22} {q['ip']:<15} {q['sistema']}")
    if not libres:
        print("No hay equipos nuevos que proteger.")
        return 0
    grupos: dict[str, list[dict]] = {}
    for q in libres:
        g = input(f"Grupo para {q['nombre']} ({q['ip']}) [Intro = no protegerlo]: ").strip()
        if g:
            grupos.setdefault(g[:40], []).append(q)
    if not grupos:
        return 0
    cred = {}
    for g in grupos:
        print(f"\nGrupo {g}: usuario administrador (se usa una vez y no se guarda; en blanco = solo darlos de alta)")
        u = input("  usuario: ").strip()
        cred[g] = (u, getpass.getpass("  contraseña: ") if u else "", False)
    filas = preparar(db, grupos)
    for f in filas:
        if f["estado"] == "nada":
            print(f"  {f['q']['nombre']}: {f['mensaje']}")
    instalar_todos(db, filas, cred, lambda f: print(f"  {f['q']['nombre']}: {f['mensaje']}"))
    print(f"\n{resumen(filas)}.  Panel: {direccion_panel(env)}")
    return 0 if not any(f["estado"] == "error" for f in filas) else 1


def main(argv: list[str]) -> int:
    sencillo = "--sencillo" in argv or not sys.stdout.isatty() or os.environ.get("TERM") == "dumb"
    if not sencillo:
        try:
            resultado = app_ventanas().run(mouse=True)
            if resultado:
                print(resultado)
            return 0
        except ImportError:
            print("(No está la librería de ventanas: uso el modo sencillo.)\n")
    try:
        return modo_sencillo()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
