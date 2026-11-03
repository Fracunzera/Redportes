"""Inventario de equipos a lo largo de todas las visitas, exportable a Excel (CSV)."""

from __future__ import annotations

import csv
from pathlib import Path

from redportes import visitas
from redportes.modelo import equipo_desde_dict

COLUMNAS = ["IP", "MAC", "Fabricante", "Tipo", "Nombre", "Sistema", "Puertos abiertos",
            "Hallazgos", "Primera vez", "Última vez", "Visitas en que apareció", "Estado"]


def armar(cliente: str, red: str | None = None, ruta_db: Path | None = None) -> list[dict]:
    """Un registro por equipo (por MAC, o IP si no hay MAC fija), con primera y última vez visto."""
    filas = [f for f in visitas.listar(cliente, ruta_db) if red is None or f[3] == red]
    equipos: dict[str, dict] = {}
    ultima_fecha = ""
    for id_visita, _cl, fecha, _red, _n in filas:
        r = visitas.obtener(id_visita, ruta_db)
        ultima_fecha = fecha
        for e in r["equipos"]:
            clave = equipo_desde_dict(e).clave
            reg = equipos.setdefault(clave, {"primera": fecha, "visitas": 0})
            reg.update(ultimo=e, ultima=fecha)
            reg["visitas"] += 1
    res = []
    for reg in equipos.values():
        e = reg["ultimo"]
        res.append({
            "IP": e["ip"], "MAC": e.get("mac", ""), "Fabricante": e.get("fabricante", ""),
            "Tipo": e.get("tipo", ""), "Nombre": e.get("nombre", ""), "Sistema": e.get("sistema", ""),
            "Puertos abiertos": ", ".join(str(p["numero"]) for p in e.get("puertos", [])),
            "Hallazgos": "; ".join(f'{h["nivel"]}: {h["titulo"]}' for h in e.get("hallazgos", [])),
            "Primera vez": reg["primera"].replace("T", " "),
            "Última vez": reg["ultima"].replace("T", " "),
            "Visitas en que apareció": reg["visitas"],
            "Estado": "Presente" if reg["ultima"] == ultima_fecha else "No apareció en la última visita",
        })
    import ipaddress

    res.sort(key=lambda x: int(ipaddress.IPv4Address(x["IP"])))
    return res


def exportar_csv(filas: list[dict], destino: Path) -> Path:
    """CSV con ';' y BOM: Excel en castellano lo abre directo con las columnas separadas."""
    with destino.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    return destino
