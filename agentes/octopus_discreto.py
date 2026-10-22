#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - MODO DISCRETO: que la copia no se note nunca (lo usa el agente, zerotouch_agent.py).

El usuario es lo primero. Mientras se hace una copia, un «gobernador» mira cada pocos segundos cuánto está usando
el equipo LA PERSONA (procesador y tarjeta gráfica, sin contar lo que gasta la propia copia) y la batería:

  libre ........ nadie lo está usando a fondo  -> la copia va a toda velocidad (prioridad algo baja, por educación)
  despacio ..... se está trabajando con él      -> prioridad mínima y la copia va a ratos (≈ 1/3 del tiempo)
  no molestar .. jugando, renderizando, vídeo a pantalla completa o con poca batería
                                                -> prioridad mínima y la copia casi parada (≈ 1/10 del tiempo)

Bajar de ritmo es inmediato; volver a subir espera dos medidas seguidas (para no dar tirones). «A ratos» se hace
pausando y reanudando el programa de copias (restic) muy rápido: no se pierde nada ni se corta la conexión.

Funciona con lo que trae cada sistema, sin instalar nada:
  Windows  GetSystemTimes/GetProcessTimes (procesador), contador «GPU Engine 3D» (gráfica), GetSystemPowerStatus
           (batería), SetPriorityClass y NtSuspendProcess/NtResumeProcess (prioridad y pausas).
  Linux    /proc/stat y /proc/<pid>/stat, nvidia-smi si hay gráfica NVIDIA, /sys/class/power_supply, nice/ionice
           y SIGSTOP/SIGCONT.
  macOS    ps (procesador), pmset (batería), renice y SIGSTOP/SIGCONT.

QUÉ TOCAR:
  - Cuándo se considera «ocupado» ... UMBRALES.
  - Cuánto trabaja en cada estado ... RITMO (segundos copiando, segundos en pausa).
"""
from __future__ import annotations

import os
import platform
import re
import signal
import subprocess
import threading
import time

SYSTEM = platform.system().lower()

# porcentaje que usa la persona (procesador sin contar la copia / gráfica 3D) a partir del cual se baja el ritmo
UMBRALES = {
    "despacio": {"cpu": 35, "gpu": 15},
    "no_molestar": {"cpu": 75, "gpu": 40},
    "bateria_baja": 25,   # % de batería sin enchufar a partir del cual: no molestar
}
# (segundos copiando, segundos en pausa) en cada estado; None = sin pausas
RITMO = {"libre": None, "despacio": (1.5, 2.5), "no_molestar": (0.5, 4.5)}
MEDIR_CADA = 3.0          # segundos entre medidas
NOMBRES = {"libre": "a toda velocidad", "despacio": "despacio (estás usando el equipo)",
           "no_molestar": "en modo no molestar (juego, pantalla completa o poca batería)"}


# ------------------------------------------------------------------------------------------- medir el equipo
class _Procesador:
    """Porcentaje de procesador que usa TODO lo demás (sin contar el proceso de la copia) entre dos medidas."""

    def __init__(self):
        self._antes = None

    def medir(self, pid: int | None, handle=None) -> float | None:
        try:
            ahora = self._leer(pid, handle)
        except Exception:
            return None
        if ahora is None:
            return None
        antes, self._antes = self._antes, ahora
        if antes is None:
            return None
        total = ahora[0] - antes[0]
        ocupado = ahora[1] - antes[1]
        hijo = max(0.0, ahora[2] - antes[2])
        if total <= 0:
            return None
        return max(0.0, min(100.0, (ocupado - hijo) * 100.0 / total))

    def _leer(self, pid, handle):
        if SYSTEM == "windows":
            return _win_tiempos(handle)
        if SYSTEM == "linux":
            with open("/proc/stat", encoding="ascii") as fh:
                v = [float(x) for x in fh.readline().split()[1:9]]
            total, libre = sum(v), v[3] + v[4]
            hijo = 0.0
            if pid:
                try:
                    with open(f"/proc/{pid}/stat", encoding="ascii") as fh:
                        campos = fh.read().rsplit(")", 1)[1].split()
                    hijo = float(campos[11]) + float(campos[12])   # utime + stime (en las mismas unidades)
                except (OSError, IndexError, ValueError):
                    pass
            return total, total - libre, hijo
        # macOS: ps da un % ya promediado; se convierte a «tiempos» acumulando para usar la misma cuenta
        salida = subprocess.run(["ps", "-A", "-o", "pid=,%cpu="], capture_output=True, text=True, timeout=10).stdout
        nucleos = os.cpu_count() or 1
        todo = hijo_pct = 0.0
        for linea in salida.splitlines():
            p = linea.split()
            if len(p) == 2:
                try:
                    c = float(p[1].replace(",", "."))
                except ValueError:
                    continue
                todo += c
                if pid and p[0] == str(pid):
                    hijo_pct = c
        t = time.monotonic()
        # «tiempo» = % medio * segundos transcurridos (así la resta de dos medidas da el uso del intervalo)
        base = self._antes[0] if self._antes else t - MEDIR_CADA
        dt = max(0.001, t - base)
        prev = self._antes or (base, 0.0, 0.0)
        return t, prev[1] + todo / nucleos * dt / 100.0, prev[2] + hijo_pct / nucleos * dt / 100.0


def _win_tiempos(handle):
    import ctypes
    from ctypes import wintypes

    def n(ft):
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
        return None
    total = float(n(kern) + n(user))          # el tiempo del núcleo ya incluye el tiempo libre
    ocupado = total - n(idle)
    hijo = 0.0
    if handle:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if ctypes.windll.kernel32.GetProcessTimes(wintypes.HANDLE(int(handle)), ctypes.byref(c), ctypes.byref(e),
                                                   ctypes.byref(k), ctypes.byref(u)):
            # los tiempos de proceso se suman en TODOS los núcleos; los del sistema también: misma escala
            hijo = float(n(k) + n(u))
    return total, ocupado, hijo


class _Grafica:
    """Uso de la tarjeta gráfica (3D) en %, medido en segundo plano (en Windows tarda ~1 s cada vez)."""

    def __init__(self):
        self.valor: float | None = None
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def parar(self):
        self._parar.set()

    def _bucle(self):
        pdh = _PdhGrafica() if SYSTEM == "windows" else None
        while not self._parar.is_set():
            try:
                v = pdh.medir() if pdh and pdh.ok else None
                self.valor = v if v is not None else medir_grafica()
            except Exception:
                self.valor = None
            self._parar.wait(MEDIR_CADA)


class _PdhGrafica:
    """Uso de la gráfica en Windows con los contadores del sistema por su nombre en INGLÉS (PdhAddEnglishCounter):
    así funciona igual en un Windows en español, en inglés o en cualquier idioma."""
    RUTA = r"\GPU Engine(*engtype_3D)\Utilization Percentage"

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.c, self.w = ctypes, wintypes
        self.pdh = ctypes.windll.pdh
        self.q, self.k = wintypes.HANDLE(), wintypes.HANDLE()
        self.ok = (self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.q)) == 0
                   and self.pdh.PdhAddEnglishCounterW(self.q, self.RUTA, 0, ctypes.byref(self.k)) == 0
                   and self.pdh.PdhCollectQueryData(self.q) == 0)

    def medir(self) -> float | None:
        c, w = self.c, self.w

        class Valor(c.Structure):
            _fields_ = [("CStatus", w.DWORD), ("doubleValue", c.c_double)]

        class Item(c.Structure):
            _fields_ = [("szName", w.LPWSTR), ("FmtValue", Valor)]
        if self.pdh.PdhCollectQueryData(self.q) != 0:
            return None
        tam, n = w.DWORD(0), w.DWORD(0)
        self.pdh.PdhGetFormattedCounterArrayW(self.k, 0x200, c.byref(tam), c.byref(n), None)   # PDH_FMT_DOUBLE
        if not tam.value:
            return 0.0
        buf = (c.c_byte * tam.value)()
        if self.pdh.PdhGetFormattedCounterArrayW(self.k, 0x200, c.byref(tam), c.byref(n), buf) != 0:
            return None
        items = c.cast(buf, c.POINTER(Item))
        return min(100.0, sum(max(0.0, items[i].FmtValue.doubleValue) for i in range(n.value)))


def medir_grafica() -> float | None:
    if SYSTEM == "windows":
        r = subprocess.run(["typeperf", r"\GPU Engine(*engtype_3D)\Utilization Percentage", "-sc", "1"],
                           capture_output=True, text=True, timeout=20, creationflags=0x08000000)
        filas = [l for l in r.stdout.splitlines() if l.startswith('"')]
        if len(filas) < 2:
            return None
        valores = []
        for v in filas[-1].split('","')[1:]:
            try:
                valores.append(float(v.strip('"').replace(",", ".")))
            except ValueError:
                pass
        return min(100.0, sum(valores)) if valores else 0.0
    if SYSTEM == "linux" and _hay("nvidia-smi"):
        r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", r.stdout)]
        return max(nums) if nums else None
    return None


def medir_bateria() -> tuple[bool, int | None]:
    """(enchufado, % de batería o None si no tiene batería)."""
    try:
        if SYSTEM == "windows":
            import ctypes

            class SPS(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                            ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                            ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
            s = SPS()
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
                return True, None
            sin_bateria = s.BatteryFlag == 128 or s.BatteryLifePercent == 255
            return s.ACLineStatus != 0, None if sin_bateria else int(s.BatteryLifePercent)
        if SYSTEM == "linux":
            base = "/sys/class/power_supply"
            pct, enchufado = None, True
            for d in os.listdir(base) if os.path.isdir(base) else []:
                tipo = _leer(f"{base}/{d}/type")
                if tipo == "Battery":
                    try:
                        pct = int(_leer(f"{base}/{d}/capacity") or "")
                    except ValueError:
                        pass
                    if _leer(f"{base}/{d}/status") == "Discharging":
                        enchufado = False
            return enchufado, pct
        if SYSTEM == "darwin":
            r = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"(\d+)%", r)
            return ("AC Power" in r or "corriente alterna" in r.lower()), (int(m.group(1)) if m else None)
    except Exception:
        pass
    return True, None


def _leer(ruta):
    try:
        with open(ruta, encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _hay(prog):
    from shutil import which
    return which(prog) is not None


def decidir(cpu: float | None, gpu: float | None, enchufado: bool, bateria: int | None,
            cuidar_bateria: bool = True) -> tuple[str, str]:
    """El estado que toca con estas medidas, y por qué (para el registro y el panel)."""
    u = UMBRALES
    if cuidar_bateria and not enchufado and bateria is not None and bateria <= u["bateria_baja"]:
        return "no_molestar", f"batería al {bateria}% sin enchufar"
    if gpu is not None and gpu >= u["no_molestar"]["gpu"]:
        return "no_molestar", f"gráfica al {gpu:.0f}% (juego o vídeo)"
    if cpu is not None and cpu >= u["no_molestar"]["cpu"]:
        return "no_molestar", f"procesador al {cpu:.0f}% (lo estás usando a fondo)"
    if cuidar_bateria and not enchufado and bateria is not None:
        return "despacio", f"sin enchufar ({bateria}%)"
    if gpu is not None and gpu >= u["despacio"]["gpu"]:
        return "despacio", f"gráfica al {gpu:.0f}%"
    if cpu is not None and cpu >= u["despacio"]["cpu"]:
        return "despacio", f"procesador al {cpu:.0f}%"
    return "libre", "nadie lo está usando a fondo"


_ORDEN = {"libre": 0, "despacio": 1, "no_molestar": 2}


# ------------------------------------------------------------------------------------------- actuar sobre la copia
def _win_prioridad(handle, baja: bool):
    import ctypes
    IDLE, BELOW_NORMAL = 0x40, 0x4000
    ctypes.windll.kernel32.SetPriorityClass(ctypes.c_void_p(int(handle)), IDLE if baja else BELOW_NORMAL)


def _win_pausa(handle, pausar: bool):
    import ctypes
    f = ctypes.windll.ntdll.NtSuspendProcess if pausar else ctypes.windll.ntdll.NtResumeProcess
    f(ctypes.c_void_p(int(handle)))


def poner_prioridad(proc: subprocess.Popen, baja: bool) -> None:
    try:
        if SYSTEM == "windows":
            _win_prioridad(proc._handle, baja)  # type: ignore[attr-defined]
            return
        os.setpriority(os.PRIO_PROCESS, proc.pid, 19 if baja else 10)
        if SYSTEM == "linux" and _hay("ionice"):
            subprocess.run(["ionice", "-c", "3" if baja else "2", *([] if baja else ["-n", "7"]), "-p", str(proc.pid)],
                           capture_output=True, timeout=10)
    except Exception:
        pass


def pausar(proc: subprocess.Popen, si: bool) -> None:
    try:
        if SYSTEM == "windows":
            _win_pausa(proc._handle, si)  # type: ignore[attr-defined]
        else:
            os.kill(proc.pid, signal.SIGSTOP if si else signal.SIGCONT)
    except Exception:
        pass


def bajar_prioridad_propia() -> None:
    """El propio agente (vigilancia de ransomware, consultas al servidor) también en segundo plano."""
    try:
        if SYSTEM == "windows":
            import ctypes
            BELOW_NORMAL, BACKGROUND_BEGIN = 0x4000, 0x00100000
            h = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(h, BELOW_NORMAL)
            ctypes.windll.kernel32.SetPriorityClass(h, BACKGROUND_BEGIN)   # también disco y memoria en baja
        else:
            os.nice(10)
    except Exception:
        pass


class Resultado(subprocess.CompletedProcess):
    """Como subprocess.CompletedProcess, con lo que ha hecho el gobernador (segundos en cada estado)."""
    discreto: dict


def ejecutar(cmd: list[str], env: dict | None = None, timeout: int = 3600, cuidar_bateria: bool = True,
             log=None, medir=None) -> Resultado:
    """Ejecuta la copia vigilada por el gobernador. `medir` (pruebas) sustituye a la medida real del equipo:
    función sin argumentos que devuelve (cpu, gpu, enchufado, bateria)."""
    flags = (0x08000000 | 0x40) if SYSTEM == "windows" else 0   # sin ventana y con prioridad mínima desde el inicio
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                                creationflags=flags, **({} if SYSTEM == "windows" else {"preexec_fn": _empezar_bajo}))
    except FileNotFoundError as exc:
        r = Resultado(cmd, 127, "", f"no encontrado: {exc}")
        r.discreto = {}
        return r
    salida, errores = [], []
    lectores = [threading.Thread(target=lambda: salida.append(proc.stdout.read()), daemon=True),
                threading.Thread(target=lambda: errores.append(proc.stderr.read()), daemon=True)]
    for t in lectores:
        t.start()

    cpu_m, gpu_m = _Procesador(), (None if medir else _Grafica())
    # empieza con la prioridad mínima (ya nace así) y sin pausas; la primera medida decide
    estado, motivo, mejoras, motivo_lento = "libre", "", 0, ""
    segundos = {"libre": 0.0, "despacio": 0.0, "no_molestar": 0.0}
    cambios: list[str] = []
    inicio = ultimo = time.monotonic()
    proxima_medida = inicio
    en_pausa = False
    tramo_fin = inicio
    try:
        while proc.poll() is None:
            ahora = time.monotonic()
            if ahora - inicio > timeout:
                proc.kill()
                break
            if ahora >= proxima_medida:
                proxima_medida = ahora + MEDIR_CADA
                if medir:
                    cpu, gpu, enchufado, bat = medir()
                else:
                    cpu = cpu_m.medir(proc.pid, getattr(proc, "_handle", None))
                    gpu = gpu_m.valor
                    enchufado, bat = medir_bateria()
                nuevo, por_que = decidir(cpu, gpu, enchufado, bat, cuidar_bateria)
                if _ORDEN[nuevo] > _ORDEN[estado]:
                    mejoras = 0                      # bajar de ritmo: al momento
                elif _ORDEN[nuevo] < _ORDEN[estado]:
                    mejoras += 1                     # subir: solo tras dos medidas seguidas
                    if mejoras < 2:
                        nuevo = estado
                else:
                    mejoras = 0
                    motivo = por_que
                if nuevo != estado:
                    cambios.append(f"{time.strftime('%H:%M:%S')} {NOMBRES[nuevo]} ({por_que})")
                    if log:
                        log(f"Copia {NOMBRES[nuevo]}: {por_que}")
                    estado, motivo, mejoras = nuevo, por_que, 0
                    if estado != "libre":
                        motivo_lento = por_que
                    poner_prioridad(proc, estado != "libre")
                    tramo_fin = ahora
            ritmo = RITMO[estado]
            if ritmo is None:
                if en_pausa:
                    pausar(proc, False)
                    en_pausa = False
            elif ahora >= tramo_fin:
                en_pausa = not en_pausa
                pausar(proc, en_pausa)
                tramo_fin = ahora + (ritmo[1] if en_pausa else ritmo[0])
            segundos[estado] += ahora - ultimo
            ultimo = ahora
            time.sleep(0.1)
    finally:
        if en_pausa:
            pausar(proc, False)
        if gpu_m:
            gpu_m.parar()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
    for t in lectores:
        t.join(timeout=30)
    rc = proc.returncode if proc.returncode is not None else 124
    r = Resultado(cmd, rc, "".join(salida), "".join(errores) + ("" if rc != 124 else "\ntimeout"))
    r.discreto = dict({k: int(v) for k, v in segundos.items()}, cambios=cambios[-20:], ultimo_motivo=motivo_lento)
    return r


def _empezar_bajo():   # en Linux/Mac, el programa de copias ya nace con la prioridad mínima
    try:
        os.nice(19)
    except OSError:
        pass


def resumen(d: dict) -> str:
    """Frase para el usuario: cuánto fue despacio y por qué."""
    if not d:
        return ""
    lento = d.get("despacio", 0) + d.get("no_molestar", 0)
    if lento < 30:
        return "La copia fue a toda velocidad: no estabas usando el equipo a fondo."
    m = max(1, round(lento / 60))
    return (f"La copia fue más despacio durante {m} min para no molestarte"
            + (f": {d.get('ultimo_motivo')}" if d.get("ultimo_motivo") else "") + ".")
