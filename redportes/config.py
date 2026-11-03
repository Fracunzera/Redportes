"""Configuración local de Redportes (config.json en la carpeta de datos)."""

from __future__ import annotations

import json

from redportes.sistema import carpeta_datos


def ruta():
    return carpeta_datos() / "config.json"


def leer() -> dict:
    try:
        return json.loads(ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar(cfg: dict) -> None:
    ruta().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
