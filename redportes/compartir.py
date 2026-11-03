"""Versión «para compartir» de un resultado: tapa IPs, MACs y nombres.

Sirve para publicar capturas, pedir ayuda o reportar un error sin exponer la red.
Mantiene lo necesario para entender el informe: el último número de cada IP, el
fabricante de cada MAC (los primeros 3 bytes) y los tipos de equipo.
"""

from __future__ import annotations

import copy
import ipaddress
import re

_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC = re.compile(r"\b([0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2})[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}\b")
_PUBLICAS_CONOCIDAS = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "208.67.222.222", "208.67.220.220"}


def tapar_ip(ip: str) -> str:
    try:
        d = ipaddress.IPv4Address(ip)
    except ValueError:
        return ip
    if ip.startswith("255.") or ip in ("0.0.0.0",) or ip in _PUBLICAS_CONOCIDAS or d.is_loopback:
        return ip
    if d in ipaddress.IPv4Network("100.64.0.0/10"):
        return "100.64.x.x"
    if d.is_private:
        return f"x.x.x.{ip.rsplit('.', 1)[1]}"
    return "x.x.x.x"


def tapar_texto(texto: str) -> str:
    texto = _IP.sub(lambda m: tapar_ip(m.group()), texto)
    return _MAC.sub(lambda m: m.group(1).upper().replace("-", ":") + ":xx:xx:xx", texto)


def _recorrer(obj):
    if isinstance(obj, dict):
        return {k: _recorrer(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_recorrer(v) for v in obj]
    if isinstance(obj, str):
        return tapar_texto(obj)
    return obj


def anonimizar(r: dict) -> dict:
    """Copia del resultado con los datos identificatorios tapados."""
    a = copy.deepcopy(r)
    a["cliente"] = "Red de ejemplo" if a.get("cliente") else ""
    nombres = {}
    for e in a.get("equipos", []):
        if e.get("nombre"):
            nombres[e["nombre"]] = "este-equipo" if e.get("es_este_equipo") else f"equipo-{len(nombres) + 1}"
            e["nombre"] = nombres[e["nombre"]]
    el = a.get("equipo_local")
    if el:
        if el.get("sistema"):
            el["sistema"]["nombre"] = "este-equipo"
        if el.get("wifi"):
            el["wifi"]["ssid"] = "(oculto)"
            el["wifi"].pop("bssid", None)
        if el.get("proxy"):
            el["proxy"] = "(configurado)"
        el["hosts"] = ["(oculto)"] * len(el.get("hosts") or [])
    inet = a.get("internet") or {}
    if inet.get("shodan"):
        inet["shodan"]["nombres"] = []
    a = _recorrer(a)

    # Los nombres viejos también pueden aparecer dentro de textos (hallazgos, etc.).
    def reemplazar_nombres(obj):
        if isinstance(obj, dict):
            return {k: reemplazar_nombres(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [reemplazar_nombres(v) for v in obj]
        if isinstance(obj, str):
            for viejo, nuevo in nombres.items():
                obj = obj.replace(viejo, nuevo)
        return obj

    a = reemplazar_nombres(a) if nombres else a
    a["compartible"] = True
    return a


def anonimizar_cambios(c: dict) -> dict:
    c = copy.deepcopy(c)
    for lista in ("nuevos", "faltan"):
        for e in c.get(lista, []):
            if e.get("nombre"):
                e["nombre"] = "equipo"
    for x in c.get("cambios", []):
        x["nombre"] = ""
    return _recorrer(c)
