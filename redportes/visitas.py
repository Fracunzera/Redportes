"""Historial de visitas por cliente (SQLite local) y comparación entre visitas."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from redportes.modelo import equipo_desde_dict
from redportes.sistema import carpeta_datos


def _conectar(ruta: Path | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(ruta or carpeta_datos() / "visitas.db")
    c.execute("""CREATE TABLE IF NOT EXISTS visitas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente TEXT NOT NULL,
        fecha TEXT NOT NULL,
        red TEXT NOT NULL,
        datos TEXT NOT NULL)""")
    return c


def guardar(resultado: dict, ruta: Path | None = None) -> int:
    with _conectar(ruta) as c:
        cur = c.execute("INSERT INTO visitas (cliente, fecha, red, datos) VALUES (?, ?, ?, ?)",
                        (resultado.get("cliente") or "", resultado["fecha"], resultado["red"],
                         json.dumps(resultado, ensure_ascii=False)))
        return cur.lastrowid


def anterior(cliente: str, red: str, antes_de: int | None = None,
             ruta: Path | None = None) -> dict | None:
    """Última visita al mismo cliente y red (anterior a la indicada)."""
    with _conectar(ruta) as c:
        fila = c.execute(
            "SELECT datos FROM visitas WHERE cliente = ? AND red = ? AND id < ? "
            "ORDER BY id DESC LIMIT 1",
            (cliente or "", red, antes_de if antes_de is not None else 2**62)).fetchone()
    return json.loads(fila[0]) if fila else None


def obtener(id_visita: int, ruta: Path | None = None) -> dict | None:
    with _conectar(ruta) as c:
        fila = c.execute("SELECT datos FROM visitas WHERE id = ?", (id_visita,)).fetchone()
    return json.loads(fila[0]) if fila else None


def listar(cliente: str | None = None, ruta: Path | None = None) -> list[tuple]:
    with _conectar(ruta) as c:
        if cliente is None:
            q = c.execute("SELECT id, cliente, fecha, red, datos FROM visitas ORDER BY id")
        else:
            q = c.execute("SELECT id, cliente, fecha, red, datos FROM visitas WHERE cliente = ? "
                          "ORDER BY id", (cliente,))
        return [(i, cl, f, r, len(json.loads(d)["equipos"])) for i, cl, f, r, d in q.fetchall()]


def comparar(previo: dict, actual: dict) -> dict:
    """Qué cambió entre dos visitas: equipos nuevos, que ya no están y cambios de puertos/IP."""
    a = {equipo_desde_dict(e).clave: e for e in previo["equipos"]}
    b = {equipo_desde_dict(e).clave: e for e in actual["equipos"]}
    nuevos = [b[k] for k in b if k not in a]
    faltan = [a[k] for k in a if k not in b]
    cambios = []
    for k in a.keys() & b.keys():
        ea, eb = a[k], b[k]
        detalle = []
        if ea["ip"] != eb["ip"]:
            detalle.append(f"cambió de IP: {ea['ip']} → {eb['ip']}")
        pa = {p["numero"] for p in ea["puertos"]}
        pb = {p["numero"] for p in eb["puertos"]}
        # Solo comparamos puertos revisados en ambas visitas.
        comunes = set(previo.get("puertos_revisados", [])) & set(actual.get("puertos_revisados", []))
        abiertos = sorted((pb - pa) & comunes)
        cerrados = sorted((pa - pb) & comunes)
        if abiertos:
            detalle.append("puertos nuevos: " + ", ".join(map(str, abiertos)))
        if cerrados:
            detalle.append("puertos cerrados: " + ", ".join(map(str, cerrados)))
        if detalle:
            cambios.append({"ip": eb["ip"], "nombre": eb.get("nombre") or eb.get("fabricante") or "",
                            "detalle": detalle})
    return {"desde": previo["fecha"], "nuevos": nuevos, "faltan": faltan, "cambios": cambios}
