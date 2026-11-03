"""Utilidades para hablar con el sistema operativo sin depender de una plataforma."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

SO = platform.system()  # "Linux", "Windows", "Darwin"
ES_WINDOWS = SO == "Windows"
ES_MAC = SO == "Darwin"


def tiene(programa: str) -> bool:
    return shutil.which(programa) is not None


def ejecutar(cmd: list[str], timeout: float = 10) -> str:
    """Ejecuta un comando y devuelve su salida estándar (vacía si falla)."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
            # En Windows evita que se abra una ventana de consola por cada ping.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return r.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def es_admin() -> bool:
    if ES_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def carpeta_datos() -> Path:
    """Carpeta donde se guardan visitas y la base de fabricantes."""
    if ES_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif ES_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "redportes"
    d.mkdir(parents=True, exist_ok=True)
    return d
