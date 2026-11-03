"""Puntaje de salud de la red (0 a 100), fácil de explicar a alguien que no es técnico."""

from __future__ import annotations

# Descuento por hallazgo y tope por nivel, para que diez cámaras iguales no hundan el número.
_DESCUENTO = {"alto": (20, 60), "medio": (5, 30), "bajo": (2, 10)}


def calcular(r: dict) -> dict:
    """Devuelve {'puntaje', 'estado', 'color', 'motivos'} a partir de un resultado de escaneo."""
    from redportes.escaneo import todos_los_hallazgos

    hall = todos_los_hallazgos(r)
    puntaje = 100
    motivos = []
    for nivel, (por_uno, tope) in _DESCUENTO.items():
        n = sum(1 for h in hall if h.nivel == nivel)
        if n:
            menos = min(n * por_uno, tope)
            puntaje -= menos
            nombre = {"alto": "grave", "medio": "medio", "bajo": "leve"}[nivel]
            motivos.append(f"{n} hallazgo{'s' if n > 1 else ''} {nombre}{'s' if n > 1 else ''} (−{menos})")

    equipos = [e for e in r.get("equipos", []) if not e.get("es_este_equipo")]
    desconocidos = sum(1 for e in equipos if (e.get("tipo") or "Desconocido") == "Desconocido")
    if desconocidos:
        menos = min(desconocidos, 10)
        puntaje -= menos
        motivos.append(f"{desconocidos} equipo{'s' if desconocidos > 1 else ''} sin identificar (−{menos})")

    inet = r.get("internet") or {}
    wan = r.get("wan") or {}
    if inet.get("doble_nat") or wan.get("tipo") == "privada":
        puntaje -= 3
        motivos.append("doble NAT (−3)")

    if any(h.nivel == "alto" for h in hall):
        puntaje = min(puntaje, 74)  # con un problema grave, la red nunca figura como "Buena"
    puntaje = max(0, puntaje)
    if puntaje >= 80:
        estado, color = "Buena", "#16a34a"
    elif puntaje >= 60:
        estado, color = "Mejorable", "#ca8a04"
    else:
        estado, color = "En riesgo", "#dc2626"
    return {"puntaje": puntaje, "estado": estado, "color": color,
            "motivos": motivos or ["sin observaciones"]}
