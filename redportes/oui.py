"""Fabricante a partir de la MAC.

Orden de búsqueda:
1. Base completa de la IEEE, si se bajó con `redportes actualizar-oui`.
2. La base de la IEEE que viene con el instalador de Windows (recursos/oui.csv).
3. La base que trae nmap, si está instalado.
4. Una lista mínima incorporada con fabricantes habituales en redes de pymes.
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
    for ieee in (Path(__file__).parent / "recursos" / "oui.csv", _ruta_ieee()):
        if ieee.exists():
            with ieee.open(newline="", encoding="utf-8", errors="replace") as f:
                for fila in csv.DictReader(f):
                    pref = (fila.get("Assignment") or "").upper()
                    if len(pref) == 6:
                        tabla[pref] = (fila.get("Organization Name") or "").strip()
    return tabla


def cantidad() -> int:
    return len(_tabla())


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


URL_WIRESHARK = "https://www.wireshark.org/download/automated/data/manuf"
_UA = "Mozilla/5.0 (compatible; redportes; +https://github.com/Fracunzera/Redportes)"


def _bajar(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def parsear_manuf(texto: str) -> list[tuple[str, str]]:
    """Formato de Wireshark: 'XX:XX:XX<TAB>Corto<TAB>Nombre largo'. Solo prefijos de 24 bits."""
    res = []
    for linea in texto.splitlines():
        if not linea or linea.startswith("#"):
            continue
        partes = linea.split("\t")
        pref = partes[0].strip()
        if "/" in pref or len(partes) < 2:
            continue
        pref = pref.replace(":", "").replace("-", "").upper()
        if len(pref) == 6:
            res.append((pref, (partes[2] if len(partes) > 2 else partes[1]).strip()))
    return res


def actualizar_base(destino: Path | None = None) -> int:
    """Baja la base de fabricantes (IEEE; si no responde, la de Wireshark).

    Devuelve la cantidad de registros guardados.
    """
    errores = []
    filas: list[tuple[str, str]] = []
    try:
        texto = _bajar(URL_IEEE, 40)
        filas = [((f.get("Assignment") or "").upper(), (f.get("Organization Name") or "").strip())
                 for f in csv.DictReader(io.StringIO(texto))]
    except Exception as e:  # noqa: BLE001
        errores.append(f"IEEE: {e}")
    if len(filas) < 1000:
        try:
            filas = parsear_manuf(_bajar(URL_WIRESHARK, 40))
        except Exception as e:  # noqa: BLE001
            errores.append(f"Wireshark: {e}")
    if len(filas) < 1000:
        raise RuntimeError("No se pudo bajar la base de fabricantes. " + " / ".join(errores))
    salida = io.StringIO()
    w = csv.writer(salida)
    w.writerow(["Registry", "Assignment", "Organization Name", "Organization Address"])
    for pref, nombre in filas:
        if len(pref) == 6:
            w.writerow(["MA-L", pref, nombre, ""])
    (destino or _ruta_ieee()).write_text(salida.getvalue(), encoding="utf-8")
    _tabla.cache_clear()
    return len(filas)
