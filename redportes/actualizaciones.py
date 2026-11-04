"""Aviso de versión nueva: consulta la última release en GitHub (como mucho una vez por día)."""

from __future__ import annotations

import json
import re
import time
import urllib.request

from redportes import __version__
from redportes.sistema import abrir_url

REPO = "Fracunzera/Redportes"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGINA = f"https://github.com/{REPO}/releases/latest"
DESCARGA_INSTALADOR = f"https://github.com/{REPO}/releases/latest/download/Redportes-Windows-instalador.exe"
DESCARGA_PORTABLE = f"https://github.com/{REPO}/releases/latest/download/Redportes-Windows-portable.zip"
DESCARGA_LINUX = f"https://github.com/{REPO}/releases/latest/download/Redportes-Linux-x86_64.AppImage"


def version_tupla(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def es_mas_nueva(remota: str, local: str = __version__) -> bool:
    return version_tupla(remota) > version_tupla(local)


def consultar(timeout: float = 6) -> dict | None:
    """{'version', 'url', 'notas'} de la última release, o None si no se pudo consultar."""
    req = urllib.request.Request(API, headers={"User-Agent": "redportes", "Accept": "application/vnd.github+json"})
    try:
        with abrir_url(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return None
    return {"version": d.get("tag_name", "").lstrip("v"), "url": d.get("html_url") or PAGINA,
            "notas": (d.get("body") or "").strip(),
            "archivos": {a["name"]: {"url": a["browser_download_url"], "tamano": a.get("size", 0)}
                         for a in d.get("assets", []) if a.get("name")}}


def hay_nueva(cfg: dict, forzar: bool = False) -> dict | None:
    """Devuelve la release si es más nueva que la instalada. Respeta 'una vez por día'."""
    act = cfg.setdefault("actualizaciones", {})
    if not forzar and time.time() - act.get("ultima_consulta", 0) < 86400:
        ultima = act.get("ultima_version")
        return {"version": ultima, "url": PAGINA, "notas": ""} if ultima and es_mas_nueva(ultima) else None
    info = consultar()
    act["ultima_consulta"] = time.time()
    if not info:
        return None
    act["ultima_version"] = info["version"]
    return info if es_mas_nueva(info["version"]) else None
