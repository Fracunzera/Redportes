"""Escaneos automáticos: tarea programada de Windows o cron en Linux/macOS."""

from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
from pathlib import Path

from redportes.sistema import ES_WINDOWS, ejecutar

PREFIJO = "Redportes"
_MARCA_CRON = "# redportes:"


def nombre_tarea(cliente: str, red: str) -> str:
    base = re.sub(r"[^\w .-]+", "_", cliente or red).strip() or "red"
    return f"{PREFIJO} - {base}"[:60]


def comando_base() -> list[str]:
    """Cómo invocar Redportes en modo consola desde una tarea programada."""
    import os

    if os.environ.get("APPIMAGE"):  # AppImage de Linux: la ruta del archivo, no la del montaje temporal
        return [os.environ["APPIMAGE"], "--programado"]
    if getattr(sys, "frozen", False):  # ejecutable empaquetado (PyInstaller)
        return [sys.executable, "--programado"]
    py = Path(sys.executable)
    if ES_WINDOWS and py.with_name("pythonw.exe").exists():
        py = py.with_name("pythonw.exe")  # sin ventana de consola
    return [str(py), "-m", "redportes"]


def argumentos(cliente: str, red: str, carpeta: str, internet: bool, puertos: str) -> list[str]:
    args = ["escanear", "--red", red, "--avisar", "--carpeta", carpeta, "-p", puertos]
    if cliente:
        args += ["--cliente", cliente]
    if internet:
        args.append("--internet")
    return args


def _validar_hora(hora: str) -> tuple[int, int]:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", hora.strip())
    if not m:
        raise ValueError("La hora tiene que ser HH:MM, por ejemplo 08:30.")
    return int(m.group(1)), int(m.group(2))


def crear(cliente: str, red: str, hora: str, carpeta: str, internet: bool = False,
          puertos: str = "rapido") -> str:
    """Crea (o reemplaza) la tarea diaria. Devuelve un texto para mostrar al usuario."""
    hh, mm = _validar_hora(hora)
    nombre = nombre_tarea(cliente, red)
    cmd = comando_base() + argumentos(cliente, red, carpeta, internet, puertos)
    if ES_WINDOWS:
        tr = subprocess.list2cmdline(cmd)
        if len(tr) > 261:
            raise ValueError("El comando queda demasiado largo para el Programador de tareas. "
                             "Usá un nombre de cliente más corto.")
        r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", f"{hh:02d}:{mm:02d}",
                            "/TN", nombre, "/TR", tr], capture_output=True, text=True, errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip() or "schtasks falló")
        return (f"Listo: «{nombre}» escanea {red} todos los días a las {hh:02d}:{mm:02d}. "
                "Corre mientras tu sesión de Windows esté iniciada.")
    linea = f"{mm} {hh} * * * {subprocess.list2cmdline(cmd)} >/dev/null 2>&1 {_MARCA_CRON}{nombre}"
    actual = [x for x in _crontab().splitlines() if not x.endswith(f"{_MARCA_CRON}{nombre}")]
    _escribir_crontab("\n".join(actual + [linea]) + "\n")
    return f"Listo: «{nombre}» escanea {red} todos los días a las {hh:02d}:{mm:02d} (cron)."


def _crontab() -> str:
    return ejecutar(["crontab", "-l"])


def _escribir_crontab(texto: str) -> None:
    try:
        r = subprocess.run(["crontab", "-"], input=texto, text=True, capture_output=True)
    except OSError:
        raise RuntimeError("No se encontró el comando crontab (instalá el paquete cron).") from None
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "No se pudo escribir el crontab.")


def listar() -> list[str]:
    if ES_WINDOWS:
        salida = ejecutar(["schtasks", "/Query", "/FO", "CSV", "/NH"])
        nombres = {fila[0].lstrip("\\") for fila in csv.reader(io.StringIO(salida)) if fila}
        return sorted(n for n in nombres if n.startswith(PREFIJO))
    return [x.split(_MARCA_CRON, 1)[1] for x in _crontab().splitlines() if _MARCA_CRON in x]


def borrar(nombre: str) -> None:
    if ES_WINDOWS:
        r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", nombre], capture_output=True, text=True,
                           errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip())
        return
    lineas = [x for x in _crontab().splitlines() if not x.endswith(f"{_MARCA_CRON}{nombre}")]
    _escribir_crontab("\n".join(lineas) + "\n")
