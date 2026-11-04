"""Utilidades para hablar con el sistema operativo sin depender de una plataforma."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SO = platform.system()  # "Linux", "Windows", "Darwin"
ES_WINDOWS = SO == "Windows"
ES_MAC = SO == "Darwin"


def tiene(programa: str) -> bool:
    return shutil.which(programa) is not None


# ---------------------------------------------------------------- entorno del ejecutable empaquetado

# Dónde guarda cada distribución los certificados raíz. El Python empaquetado (AppImage) trae un
# OpenSSL armado en Ubuntu que solo mira la ruta de Debian/Ubuntu: en Fedora no confiaría en nadie.
_CERTIFICADOS = (
    "/etc/ssl/certs/ca-certificates.crt",                 # Debian, Ubuntu, Mint, Arch
    "/etc/pki/tls/certs/ca-bundle.crt",                   # Fedora, RHEL, CentOS, Rocky
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora (otra ruta)
    "/etc/ssl/ca-bundle.pem",                             # openSUSE
    "/etc/ssl/cert.pem",                                  # Alpine, macOS
)


def _preparar_entorno() -> None:
    if ES_WINDOWS or not getattr(sys, "frozen", False):
        return
    if not os.environ.get("SSL_CERT_FILE"):
        for ruta in _CERTIFICADOS:
            if os.path.exists(ruta):
                os.environ["SSL_CERT_FILE"] = ruta
                break


def entorno_sistema() -> dict | None:
    """Entorno para lanzar programas del sistema (resolvectl, nmcli…) desde el ejecutable empaquetado.

    PyInstaller apunta LD_LIBRARY_PATH a sus propias bibliotecas; si un programa del sistema las
    hereda puede fallar. Se restaura el valor original.
    """
    if ES_WINDOWS or not getattr(sys, "frozen", False):
        return None
    env = dict(os.environ)
    for var in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
        original = env.pop(f"{var}_ORIG", None)
        if original is not None:
            env[var] = original
        else:
            env.pop(var, None)
    return env


_preparar_entorno()


def ejecutar_detallado(cmd: list[str], timeout: float = 10, encoding: str | None = None,
                       cancelado=None) -> tuple[str, str]:
    """Ejecuta un comando. Devuelve (salida, estado) con estado 'ok', 'tiempo', 'cancelado' o 'error'.

    - stdin vacío: en el ejecutable de Windows (sin consola) algunos programas, como nmap,
      se quedaban esperando una entrada que nunca llega.
    - Se puede cortar en cualquier momento con `cancelado()`.
    En Windows, los comandos de consola (netsh, ipconfig) escriben en la página de códigos OEM:
    con encoding="oem" se leen bien los acentos («Señal», «Autenticación»).
    """
    if encoding == "oem" and not ES_WINDOWS:
        encoding = None
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding=encoding, errors="replace",
            # En Windows evita que se abra una ventana de consola por cada ping.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=entorno_sistema(),
        )
    except OSError:
        return "", "error"
    import time

    fin = time.monotonic() + timeout
    while True:
        try:
            salida, _ = proc.communicate(timeout=0.3)
            return salida or "", "ok"
        except subprocess.TimeoutExpired:
            pass
        estado = "cancelado" if cancelado and cancelado() else "tiempo" if time.monotonic() > fin else ""
        if estado:
            proc.kill()
            try:
                salida, _ = proc.communicate(timeout=3)
            except subprocess.SubprocessError:
                salida = ""
            return salida or "", estado


def ejecutar(cmd: list[str], timeout: float = 10, encoding: str | None = None, cancelado=None) -> str:
    """Ejecuta un comando y devuelve su salida estándar (vacía si falla)."""
    return ejecutar_detallado(cmd, timeout, encoding, cancelado)[0]


def es_admin() -> bool:
    if ES_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def carpeta_programa() -> Path:
    """Carpeta del ejecutable (versión empaquetada) o del paquete (instalado con pip)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def es_portable() -> bool:
    """Versión portable: hay un archivo «portable.txt» al lado del ejecutable (o REDPORTES_PORTABLE=1)."""
    if os.environ.get("REDPORTES_PORTABLE") == "1":
        return True
    return getattr(sys, "frozen", False) and (carpeta_programa() / "portable.txt").exists()


def carpeta_datos() -> Path:
    """Carpeta donde se guardan visitas, configuración y la base de fabricantes."""
    if es_portable():
        d = carpeta_programa() / "datos"
        d.mkdir(parents=True, exist_ok=True)
        return d
    if ES_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif ES_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "redportes"
    d.mkdir(parents=True, exist_ok=True)
    return d
