"""Fabricante a partir de la MAC.

Orden de búsqueda:
1. Base completa de la IEEE, si se bajó con `redportes actualizar-oui`.
2. La base que trae nmap, si está instalado.
3. Una lista mínima incorporada con fabricantes habituales en redes de pymes.
"""

from __future__ import annotations

import csv
import io
import urllib.request
from functools import lru_cache
from pathlib import Path

from redportes.sistema import carpeta_datos

URL_IEEE = "https://standards-oui.ieee.org/oui/oui.csv"

_INCORPORADOS = {
    # Virtualización
    "000C29": "VMware", "005056": "VMware", "000569": "VMware",
    "080027": "VirtualBox", "525400": "QEMU/KVM", "BC2411": "Proxmox",
    "00155D": "Microsoft Hyper-V", "00163E": "Xen",
    # Raspberry Pi
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi",
    "D83ADD": "Raspberry Pi",
    # MikroTik
    "4C5E0C": "MikroTik", "6C3B6B": "MikroTik", "B869F4": "MikroTik", "CC2DE0": "MikroTik",
    "D4CA6D": "MikroTik", "E48D8C": "MikroTik", "488F5A": "MikroTik", "744D28": "MikroTik",
    "DC2C6E": "MikroTik", "2CC81B": "MikroTik", "64D154": "MikroTik", "18FD74": "MikroTik",
    "085531": "MikroTik", "C4AD34": "MikroTik",
    # Ubiquiti
    "24A43C": "Ubiquiti", "0418D6": "Ubiquiti", "44D9E7": "Ubiquiti", "687251": "Ubiquiti",
    "788A20": "Ubiquiti", "802AA8": "Ubiquiti", "F09FC2": "Ubiquiti", "FCECDA": "Ubiquiti",
    "B4FBE4": "Ubiquiti", "18E829": "Ubiquiti", "7483C2": "Ubiquiti", "E063DA": "Ubiquiti",
    "245A4C": "Ubiquiti", "68D79A": "Ubiquiti", "70A741": "Ubiquiti",
    # Cámaras
    "4419B6": "Hikvision", "4CBD8F": "Hikvision", "C056E3": "Hikvision", "BCAD28": "Hikvision",
    "54C415": "Hikvision", "2857BE": "Hikvision", "A41437": "Hikvision", "C42F90": "Hikvision",
    "3CEF8C": "Dahua", "9002A9": "Dahua", "E0508B": "Dahua", "4C11BF": "Dahua",
    "BC325F": "Dahua", "38AF29": "Dahua", "9C1463": "Dahua",
}


def mac_aleatoria(mac: str) -> bool:
    """MAC administrada localmente (típica de celulares y notebooks con MAC privada)."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


def _ruta_ieee() -> Path:
    return carpeta_datos() / "oui.csv"


def _rutas_nmap() -> list[Path]:
    return [
        Path("/usr/share/nmap/nmap-mac-prefixes"),
        Path("/usr/local/share/nmap/nmap-mac-prefixes"),
        Path("/opt/homebrew/share/nmap/nmap-mac-prefixes"),
        Path(r"C:\Program Files (x86)\Nmap\nmap-mac-prefixes"),
        Path(r"C:\Program Files\Nmap\nmap-mac-prefixes"),
    ]


@lru_cache(maxsize=1)
def _tabla() -> dict[str, str]:
    tabla = dict(_INCORPORADOS)
    for ruta in _rutas_nmap():
        if ruta.exists():
            for linea in ruta.read_text(errors="replace").splitlines():
                if linea and not linea.startswith("#"):
                    pref, _, nombre = linea.partition(" ")
                    if len(pref) == 6:
                        tabla[pref.upper()] = nombre.strip()
            break
    ieee = _ruta_ieee()
    if ieee.exists():
        with ieee.open(newline="", encoding="utf-8", errors="replace") as f:
            for fila in csv.DictReader(f):
                pref = (fila.get("Assignment") or "").upper()
                if len(pref) == 6:
                    tabla[pref] = (fila.get("Organization Name") or "").strip()
    return tabla


def fabricante(mac: str) -> str:
    if not mac:
        return ""
    pref = mac.replace(":", "").upper()[:6]
    nombre = _tabla().get(pref, "")
    if nombre:
        return nombre
    if mac_aleatoria(mac):
        return "MAC aleatoria"
    return ""


def actualizar_base() -> int:
    """Baja la base de fabricantes de la IEEE. Devuelve la cantidad de registros."""
    req = urllib.request.Request(URL_IEEE, headers={"User-Agent": "redportes"})
    with urllib.request.urlopen(req, timeout=60) as r:
        datos = r.read()
    texto = datos.decode("utf-8", errors="replace")
    filas = sum(1 for _ in csv.DictReader(io.StringIO(texto)))
    if filas < 1000:
        raise RuntimeError("La descarga no parece la base de la IEEE.")
    _ruta_ieee().write_bytes(datos)
    _tabla.cache_clear()
    return filas
