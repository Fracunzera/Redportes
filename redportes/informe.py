"""Informe HTML autocontenido (sin recursos externos), listo para imprimir a PDF."""

from __future__ import annotations

from datetime import datetime
from html import escape

from redportes import __version__
from redportes.escaneo import todos_los_hallazgos

COLORES = {
    "Router": "#2563eb", "MikroTik": "#2563eb", "Equipo de red": "#2563eb", "Ubiquiti": "#0891b2",
    "Cámara": "#db2777", "Impresora": "#7c3aed", "Teléfono": "#0d9488", "PC": "#475569",
    "Servidor": "#ca8a04", "Máquina virtual": "#ca8a04", "Raspberry": "#dc2626",
    "Celular": "#16a34a", "Este equipo": "#111827",
}
NIVEL_COLOR = {"alto": "#dc2626", "medio": "#ea580c", "bajo": "#ca8a04", "info": "#64748b"}
NIVEL_TEXTO = {"alto": "Alto", "medio": "Medio", "bajo": "Bajo", "info": "Info"}


def _color(tipo: str) -> str:
    for clave, color in COLORES.items():
        if tipo.startswith(clave) or clave in tipo:
            return color
    return "#94a3b8"


def _e(x) -> str:
    return escape(str(x if x is not None else ""))


def _corto(t: str, n: int) -> str:
    t = t or ""
    return t if len(t) <= n else t[: n - 1] + "…"


def _peor_nivel(eq: dict) -> str:
    niveles = [h["nivel"] for h in eq.get("hallazgos", [])]
    for n in ("alto", "medio", "bajo"):
        if n in niveles:
            return n
    return ""


# ---------------------------------------------------------------- mapa SVG

def mapa_svg(r: dict) -> str:
    equipos = r["equipos"]
    puerta = r.get("puerta") or ""
    resto = [e for e in equipos if e["ip"] != puerta]
    ancho, cols, paso_x, paso_y = 1000, 8, 118, 92
    filas = max(1, -(-len(resto) // cols))
    alto = 190 + filas * paso_y
    s = [f'<svg viewBox="0 0 {ancho} {alto}" xmlns="http://www.w3.org/2000/svg" '
         f'role="img" aria-label="Mapa de la red" font-family="inherit">']

    # Fila superior: router → saltos → Internet
    saltos = []
    if r.get("internet") and r["internet"].get("saltos"):
        saltos = [x for x in r["internet"]["saltos"] if x.get("ip") != puerta][:6]
    nodos = [("router", puerta or "Router")] + [("salto", x) for x in saltos] + [("internet", "")]
    xs = [60 + i * ((ancho - 140) / max(1, len(nodos) - 1)) for i in range(len(nodos))]
    y0 = 55
    for i in range(len(nodos) - 1):
        punteada = ' stroke-dasharray="5 4"' if not saltos else ""
        s.append(f'<line x1="{xs[i]:.0f}" y1="{y0}" x2="{xs[i+1]:.0f}" y2="{y0}" '
                 f'stroke="#94a3b8" stroke-width="2"{punteada}/>')
    for (tipo, dato), x in zip(nodos, xs):
        if tipo == "internet":
            s.append(f'<g transform="translate({x:.0f},{y0})"><ellipse rx="46" ry="24" '
                     f'fill="#f1f5f9" stroke="#64748b" stroke-width="1.5"/>'
                     f'<text text-anchor="middle" y="5" font-size="13" font-weight="600" '
                     f'fill="#0f172a">Internet</text></g>')
        elif tipo == "router":
            gw = next((e for e in equipos if e["ip"] == puerta), None)
            ring = NIVEL_COLOR.get(_peor_nivel(gw), "#fff") if gw else "#fff"
            sub = _corto((gw or {}).get("fabricante") or "", 22)
            s.append(f'<g transform="translate({x:.0f},{y0})"><title>Puerta de enlace {_e(dato)}</title>'
                     f'<circle r="20" fill="#2563eb" stroke="{ring}" stroke-width="4"/>'
                     f'<text text-anchor="middle" y="5" font-size="12" fill="#fff" '
                     f'font-weight="700">GW</text>'
                     f'<text x="28" y="-8" font-size="11" font-weight="600" '
                     f'fill="#0f172a">{_e(dato)}</text>'
                     f'<text x="28" y="18" font-size="10" fill="#64748b">{_e(sub)}</text></g>')
        else:
            color = {"privada": "#f59e0b", "cgnat": "#dc2626"}.get(dato.get("tipo"), "#94a3b8")
            etiqueta = {"privada": "privada", "cgnat": "CGNAT", "publica": "operador",
                        "sin respuesta": "sin respuesta"}.get(dato.get("tipo"), "")
            ms = f' · {dato["ms"]:.0f} ms' if dato.get("ms") is not None else ""
            s.append(f'<g transform="translate({x:.0f},{y0})">'
                     f'<circle r="11" fill="#fff" stroke="{color}" stroke-width="3"/>'
                     f'<text text-anchor="middle" y="4" font-size="10" fill="#0f172a">{dato["n"]}</text>'
                     f'<text text-anchor="middle" y="28" font-size="10" fill="#0f172a">'
                     f'{_e(dato.get("ip") or "*")}</text>'
                     f'<text text-anchor="middle" y="40" font-size="9" fill="#64748b">'
                     f'{_e(etiqueta + ms)}</text></g>')

    # Bus de la red local y equipos
    bus_y = 140
    if resto:
        fin_bus = 60 + (min(cols, len(resto)) - 1) * paso_x + 40
        s.append(f'<line x1="{xs[0]:.0f}" y1="{y0 + 20}" x2="{xs[0]:.0f}" y2="{bus_y}" '
                 f'stroke="#2563eb" stroke-width="2"/>')
        s.append(f'<line x1="{xs[0]:.0f}" y1="{bus_y}" x2="{max(fin_bus, xs[0]):.0f}" y2="{bus_y}" '
                 f'stroke="#2563eb" stroke-width="3"/>')
        s.append(f'<text x="{max(fin_bus, xs[0]):.0f}" y="{bus_y - 6}" text-anchor="end" '
                 f'font-size="10" fill="#2563eb">Red {_e(r["red"])}</text>')
    for i, e in enumerate(resto):
        fila, col = divmod(i, cols)
        x = 100 + col * paso_x
        y = bus_y + 40 + fila * paso_y
        if fila == 0:
            s.append(f'<line x1="{x}" y1="{bus_y}" x2="{x}" y2="{y - 16}" stroke="#cbd5e1" stroke-width="1.5"/>')
        nivel = _peor_nivel(e)
        borde = NIVEL_COLOR.get(nivel, "#fff")
        nombre = e.get("nombre") or e.get("fabricante") or e.get("tipo") or ""
        puertos = ", ".join(str(p["numero"]) for p in e.get("puertos", []))
        tip = f'{e["ip"]} — {e.get("tipo","")}\n{e.get("fabricante","")}\n{e.get("mac","")}' \
              + (f"\nPuertos: {puertos}" if puertos else "")
        letra = "★" if e.get("es_este_equipo") else (e.get("tipo") or "?")[0]
        s.append(f'<g transform="translate({x},{y})"><title>{_e(tip)}</title>'
                 f'<circle r="15" fill="{_color(e.get("tipo",""))}" stroke="{borde}" stroke-width="4"/>'
                 f'<text text-anchor="middle" y="4" font-size="11" fill="#fff" font-weight="700">'
                 f'{_e(letra)}</text>'
                 f'<text text-anchor="middle" y="32" font-size="10.5" font-weight="600" fill="#0f172a">'
                 f'{_e(e["ip"])}</text>'
                 f'<text text-anchor="middle" y="44" font-size="9" fill="#64748b">'
                 f'{_e(_corto(nombre, 20))}</text></g>')
    s.append("</svg>")
    return "".join(s)


# ---------------------------------------------------------------- HTML

def _leyenda(r: dict) -> str:
    tipos = []
    for e in r["equipos"]:
        if e["ip"] != r.get("puerta") and e.get("tipo") and e["tipo"] not in tipos:
            tipos.append(e["tipo"])
    items = "".join(
        f'<span><i style="background:{_color(t)}">{_e("★" if t == "Este equipo" else t[0])}</i>{_e(t)}</span>'
        for t in tipos)
    return f'<div class="leyenda">{items}</div>'


def _tarjeta(valor, etiqueta, color="#0f172a") -> str:
    return (f'<div class="tarjeta"><div class="valor" style="color:{color}">{_e(valor)}</div>'
            f'<div class="etq">{_e(etiqueta)}</div></div>')


def generar(r: dict, cambios: dict | None = None) -> str:
    hall = todos_los_hallazgos(r)
    cuenta = {n: sum(1 for h in hall if h.nivel == n) for n in NIVEL_COLOR}
    fecha = datetime.fromisoformat(r["fecha"]).strftime("%d/%m/%Y %H:%M")
    titulo = f"Red {r['red']}" + (f" — {r['cliente']}" if r.get("cliente") else "")
    nombres = {e["ip"]: (e.get("nombre") or e.get("fabricante") or e.get("tipo") or "") for e in r["equipos"]}

    partes = [f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(titulo)} · Redportes</title>
<style>{CSS}</style></head><body>
<header>
  <div><div class="marca">Redportes</div>
  <h1>{_e(titulo)}</h1>
  <div class="meta">{_e(fecha)} · interfaz {_e(r['interfaz']['nombre'])} ({_e(r['interfaz']['ip'])})
  · {_e(r['sistema'])} · {r['duracion_s']} s</div></div>
  <button class="no-print" onclick="window.print()">Guardar como PDF</button>
</header>
<section class="tarjetas">
  {_tarjeta(len(r['equipos']), 'equipos encontrados')}
  {_tarjeta(cuenta['alto'], 'hallazgos altos', NIVEL_COLOR['alto'])}
  {_tarjeta(cuenta['medio'], 'hallazgos medios', NIVEL_COLOR['medio'])}
  {_tarjeta(r.get('puerta') or '—', 'puerta de enlace')}
</section>
<section><h2>Mapa</h2><div class="mapa">{mapa_svg(r)}</div>
{_leyenda(r)}
<p class="nota">El borde de cada equipo indica el hallazgo más grave: rojo alto, naranja medio,
amarillo bajo. Pasá el mouse por encima para ver el detalle.</p></section>
"""]

    # Salida a Internet
    partes.append('<section><h2>Salida a Internet</h2>')
    inet = r.get("internet")
    if inet:
        if inet.get("ip_publica"):
            partes.append(f'<p>IP pública vista desde afuera: <b>{_e(inet["ip_publica"])}</b></p>')
        partes.append("<ul>" + "".join(f"<li>{_e(c)}</li>" for c in inet["conclusiones"]) + "</ul>")
    else:
        partes.append('<p class="nota">No se analizó (se activa con <code>--internet</code>, '
                      'porque implica tráfico hacia afuera).</p>')
    if r.get("dns"):
        partes.append("<p>DNS configurados: " + ", ".join(
            f'<b>{_e(d["ip"])}</b> <span class="gris">({_e(d["quien"])})</span>' for d in r["dns"]) + "</p>")
    partes.append("</section>")

    # Hallazgos
    grupos: dict[tuple, list] = {}
    for h in hall:
        grupos.setdefault((h.nivel, h.titulo), []).append(h)
    partes.append(f'<section><h2>Para revisar <span class="gris">({len(hall)} en '
                  f'{len(grupos)} temas)</span></h2>')
    if not hall:
        partes.append("<p>No se encontró nada para revisar con los puertos analizados.</p>")
    for (nivel, titulo), lista in grupos.items():
        h = lista[0]
        afectados = "".join(
            f'<li><b class="mono">{_e(x.ip)}</b> {_e(nombres.get(x.ip, ""))}'
            + (f' <span class="gris">— {_e(x.detalle)}</span>' if x.detalle else "") + "</li>"
            for x in lista)
        cant = f' <span class="gris">· {len(lista)} equipos</span>' if len(lista) > 1 else ""
        partes.append(
            f'<div class="hallazgo" style="border-left-color:{NIVEL_COLOR[nivel]}">'
            f'<div class="h-tit"><span class="nivel" style="background:{NIVEL_COLOR[nivel]}">'
            f'{NIVEL_TEXTO[nivel]}</span> {_e(titulo)}{cant}</div>'
            f'<ul class="afectados">{afectados}</ul>'
            f'<p>{_e(h.que_es)}</p><p><b>Qué hacer:</b> {_e(h.que_hacer)}</p></div>')
    partes.append("</section>")

    # Cambios
    if cambios is not None:
        desde = datetime.fromisoformat(cambios["desde"]).strftime("%d/%m/%Y")
        partes.append(f'<section><h2>Cambios desde la visita del {_e(desde)}</h2>')
        if not (cambios["nuevos"] or cambios["faltan"] or cambios["cambios"]):
            partes.append("<p>Sin cambios.</p>")
        if cambios["nuevos"]:
            partes.append("<h3>Equipos nuevos</h3><ul>" + "".join(
                f'<li><b>{_e(e["ip"])}</b> {_e(e.get("tipo",""))} '
                f'<span class="gris">{_e(e.get("fabricante") or e.get("nombre") or "")}</span></li>'
                for e in cambios["nuevos"]) + "</ul>")
        if cambios["faltan"]:
            partes.append("<h3>Ya no aparecen</h3><ul>" + "".join(
                f'<li><b>{_e(e["ip"])}</b> {_e(e.get("tipo",""))} '
                f'<span class="gris">{_e(e.get("fabricante") or e.get("nombre") or "")}</span></li>'
                for e in cambios["faltan"]) + "</ul>")
        if cambios["cambios"]:
            partes.append("<h3>Cambiaron</h3><ul>" + "".join(
                f'<li><b>{_e(c["ip"])}</b> {_e(c["nombre"])}: {_e("; ".join(c["detalle"]))}</li>'
                for c in cambios["cambios"]) + "</ul>")
        partes.append("</section>")

    # Tabla de equipos
    partes.append('<section><h2>Equipos</h2><div class="tabla"><table><thead><tr>'
                  '<th>IP</th><th>Tipo</th><th>Fabricante</th><th>MAC</th><th>Nombre</th>'
                  '<th>Sistema</th><th>Puertos abiertos</th><th>Lat.</th></tr></thead><tbody>')
    for e in r["equipos"]:
        puertos = "<br>".join(
            f'{p["numero"]} {_e(p["servicio"])}'
            + (f' <span class="gris">«{_e(_corto(p["titulo"] or p["banner"], 40))}»</span>'
               if (p["titulo"] or p["banner"]) else "")
            for p in e["puertos"]) or '<span class="gris">—</span>'
        marcas = (" ★" if e.get("es_este_equipo") else "") + (" (GW)" if e.get("es_puerta") else "")
        lat = f'{e["latencia_ms"]:.0f} ms' if e.get("latencia_ms") is not None else "—"
        partes.append(
            f'<tr><td class="mono"><b>{_e(e["ip"])}</b>{_e(marcas)}</td><td>{_e(e.get("tipo"))}</td>'
            f'<td>{_e(e.get("fabricante"))}</td><td class="mono">{_e(e.get("mac"))}</td>'
            f'<td>{_e(e.get("nombre"))}</td><td>{_e(e.get("sistema"))}</td><td>{puertos}</td>'
            f'<td class="lat">{lat}</td></tr>')
    partes.append("</tbody></table></div></section>")

    puertos_rev = r.get("puertos_revisados") or []
    partes.append(f"""<footer>
<p>Generado con Redportes {__version__}. Puertos TCP revisados: {len(puertos_rev)}
{'(con nmap)' if r.get('nmap') else '(sin nmap)'}{'' if r.get('admin') else ' · sin permisos de administrador'}.</p>
<p>Redportes no instala agentes, no prueba contraseñas, no cambia nada en los equipos y no envía
datos a Internet salvo que se use <code>--internet</code>. Es una foto del momento: un equipo apagado
o con firewall puede no aparecer.</p></footer></body></html>""")
    return "".join(partes)


CSS = """
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,Ubuntu,sans-serif;color:#0f172a;
  margin:0 auto;max-width:1100px;padding:28px 24px;line-height:1.45;background:#fff}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
  border-bottom:2px solid #0f172a;padding-bottom:14px}
.marca{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#2563eb;font-weight:700}
h1{margin:2px 0 4px;font-size:26px}
h2{font-size:18px;margin:30px 0 10px;border-bottom:1px solid #e2e8f0;padding-bottom:6px}
h3{font-size:14px;margin:14px 0 4px}
.meta,.gris,.nota{color:#64748b}.nota{font-size:13px}
button{background:#0f172a;color:#fff;border:0;border-radius:8px;padding:10px 14px;font-size:14px;cursor:pointer}
.tarjetas{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px}
.tarjeta{border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px}
.valor{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}
.etq{font-size:12px;color:#64748b}
.mapa{border:1px solid #e2e8f0;border-radius:10px;padding:8px;overflow-x:auto}
.mapa svg{width:100%;min-width:700px;height:auto;display:block}
.hallazgo{border:1px solid #e2e8f0;border-left:5px solid;border-radius:8px;padding:10px 14px;margin:10px 0;
  break-inside:avoid}
.hallazgo p{margin:6px 0 0;font-size:14px}
.h-tit{font-weight:600}
.nivel{color:#fff;font-size:11px;border-radius:4px;padding:2px 6px;margin-right:4px;text-transform:uppercase}
.tabla{overflow-x:auto}
.leyenda{display:flex;flex-wrap:wrap;gap:6px 16px;margin:10px 0 0;font-size:12px;color:#334155}
.leyenda i{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;
  border-radius:50%;color:#fff;font-style:normal;font-size:9px;font-weight:700;margin-right:5px;
  vertical-align:-3px}
.afectados{margin:6px 0 0;padding-left:18px;font-size:14px}
td.lat{white-space:nowrap}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid #e2e8f0}
th{background:#f8fafc;font-weight:600}
tr{break-inside:avoid}
.mono,code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
footer{margin-top:36px;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b}
@media (max-width:700px){.tarjetas{grid-template-columns:repeat(2,1fr)}header{flex-direction:column}}
@media print{.no-print{display:none}body{padding:0;max-width:none}.mapa svg{min-width:0}
  h2{break-after:avoid}@page{margin:14mm}}
"""
