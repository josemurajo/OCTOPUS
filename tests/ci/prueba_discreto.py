"""Prueba del MODO DISCRETO (agentes/octopus_discreto.py) en el sistema real (Linux, Windows y Mac en GitHub):
mide de verdad el equipo, baja y sube la prioridad, pausa y reanuda, y comprueba que una «copia» va casi parada
mientras el usuario juega y a toda velocidad cuando lo deja.

    python tests/ci/prueba_discreto.py
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agentes"))
import octopus_discreto as d  # noqa: E402

FALLOS = []


def chk(c, n, x=""):
    print("PASS" if c else "FAIL", n, x)
    if not c:
        FALLOS.append(n)


# 1. decidir
chk(d.decidir(5, 0, True, None)[0] == "libre", "equipo tranquilo: a toda velocidad")
chk(d.decidir(50, 0, True, None)[0] == "despacio", "trabajando con el equipo: despacio")
chk(d.decidir(10, 90, True, None)[0] == "no_molestar", "jugando (gráfica al 90%): no molestar")
chk(d.decidir(90, None, True, None)[0] == "no_molestar", "procesador a tope: no molestar")
chk(d.decidir(5, 0, False, 80)[0] == "despacio", "portátil sin enchufar: despacio")
chk(d.decidir(5, 0, False, 10)[0] == "no_molestar", "batería baja: no molestar")
chk(d.decidir(5, 0, False, 10, cuidar_bateria=False)[0] == "libre", "si no se cuida la batería, no cuenta")
chk(d.decidir(None, None, True, None)[0] == "libre", "sin medidas: no se inventa que está ocupado")

# 2. medidas reales de este equipo
enchufado, bat = d.medir_bateria()
chk(isinstance(enchufado, bool) and (bat is None or 0 <= bat <= 100), "batería: se lee sin fallar", (enchufado, bat))
p = d._Procesador()
p.medir(None)
time.sleep(1.5)
cpu = p.medir(None)
chk(cpu is not None and 0 <= cpu <= 100, "procesador: se mide (sin contar la copia)", cpu)
try:
    g = d._PdhGrafica().medir() if d.SYSTEM == "windows" else d.medir_grafica()
    chk(g is None or 0 <= g <= 100, "gráfica: se mide o se ignora si no hay", g)
except Exception as exc:
    chk(False, "gráfica: no debe romper nada", exc)

# 3. prioridad y pausas sobre un proceso de verdad
hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
d.poner_prioridad(hijo, True)
if d.SYSTEM == "windows":
    import ctypes
    clase = ctypes.windll.kernel32.GetPriorityClass(ctypes.c_void_p(int(hijo._handle)))
    chk(clase == 0x40, "prioridad mínima (IDLE) mientras molesta", hex(clase))
    d.poner_prioridad(hijo, False)
    clase = ctypes.windll.kernel32.GetPriorityClass(ctypes.c_void_p(int(hijo._handle)))
    chk(clase == 0x4000, "prioridad algo baja (BELOW_NORMAL) cuando el equipo está libre", hex(clase))
else:
    import os
    chk(os.getpriority(os.PRIO_PROCESS, hijo.pid) == 19, "prioridad mínima (nice 19) mientras molesta")
d.pausar(hijo, True)
d.pausar(hijo, False)
chk(hijo.poll() is None, "pausar y reanudar no rompe el proceso")
hijo.kill()

# 4. la «copia» de prueba: 30 pasos de 0,05 s (1,5 s si nadie la frena)
d.MEDIR_CADA = 0.5
d.RITMO["no_molestar"] = (0.2, 1.8)
d.RITMO["despacio"] = (0.4, 0.6)
COPIA = [sys.executable, "-c", "import time\nfor i in range(30):\n    time.sleep(0.05)\n    print(i, flush=True)\nprint('fin')"]

t = time.monotonic()
r = d.ejecutar(COPIA, medir=lambda: (5.0, 0.0, True, None))
libre = time.monotonic() - t
chk(r.returncode == 0 and "fin" in r.stdout, "la copia termina bien y se recoge su salida")
chk(libre < 6, "con el equipo libre va a toda velocidad", f"{libre:.1f} s")

t = time.monotonic()
r = d.ejecutar(COPIA, medir=lambda: (10.0, 95.0, True, None))
jugando = time.monotonic() - t
chk(r.returncode == 0 and "fin" in r.stdout, "jugando: la copia sigue y termina (no se pierde nada)")
chk(jugando > libre * 3 and jugando > 6, "jugando: va casi parada", f"{jugando:.1f} s frente a {libre:.1f} s")
chk(r.discreto.get("no_molestar", 0) >= 5, "apunta el tiempo en modo no molestar", r.discreto)
chk("no molestar" in d.resumen(r.discreto) or "despacio" in d.resumen(r.discreto), "frase para el usuario",
    d.resumen(r.discreto))

medidas = iter([(10.0, 95.0, True, None)] * 4)
t = time.monotonic()
r = d.ejecutar(COPIA, medir=lambda: next(medidas, (3.0, 0.0, True, None)))
chk(r.returncode == 0 and any("toda velocidad" in c for c in r.discreto.get("cambios", [])),
    "deja de jugar: vuelve a toda velocidad", r.discreto.get("cambios"))
chk(time.monotonic() - t < jugando, "y acaba antes que jugando todo el rato", f"{time.monotonic() - t:.1f} s")

print("FALLOS:", FALLOS or "ninguno")
sys.exit(1 if FALLOS else 0)
