"""Acceso en el menú de aplicaciones de Linux (archivo .desktop + ícono)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PLANTILLA = """[Desktop Entry]
Type=Application
Name=Redportes
GenericName=Escáner de red
Comment=Mapa de la red, qué es cada equipo, qué revisar e informes
Exec={exec}
Icon={icono}
Terminal=false
Categories=Network;System;Utility;
Keywords=red;escaner;nmap;wifi;dns;diagnostico;
StartupWMClass=Redportes
"""


def ejecutable() -> str:
    if os.environ.get("APPIMAGE"):
        return os.environ["APPIMAGE"]
    if getattr(sys, "frozen", False):
        return sys.executable
    gui = shutil.which("redportes-gui")
    if gui:
        return gui
    raise RuntimeError("no se encontró el comando redportes-gui")


def instalar_acceso() -> Path:
    datos = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    iconos = datos / "icons" / "hicolor" / "256x256" / "apps"
    apps = datos / "applications"
    iconos.mkdir(parents=True, exist_ok=True)
    apps.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parent / "recursos" / "icono.png", iconos / "redportes.png")
    exe = ejecutable()
    destino = apps / "redportes.desktop"
    destino.write_text(PLANTILLA.format(exec=f'"{exe}"', icono=str(iconos / "redportes.png")), encoding="utf-8")
    destino.chmod(0o755)
    return destino
