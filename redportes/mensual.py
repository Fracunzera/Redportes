"""Informe mensual de una red: evolución, cambios y pendientes, listo para presentar."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from redportes import AUTOR_URL, SITIO, __autor__, __version__, salud, visitas
from redportes.informe import CSS, NIVEL_COLOR, NIVEL_TEXTO, _e
from redportes.modelo import equipo_desde_dict

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


class SinVisitas(ValueError):
    pass


def _nombre_mes(mes: str) -> str:
    a, m = mes.split("-")
    return f"{MESES[int(m) - 1]} de {a}"


def _mes_anterior(mes: str) -> str:
    a, m = map(int, mes.split("-"))
    return f"{a - 1}-12" if m == 1 else f"{a}-{m - 1:02d}"


def _hallazgos(r: dict) -> dict[tuple, dict]:
    """(equipo, título, puerto) -> hallazgo, para comparar entre visitas."""
    res = {}
    for e in r["equipos"]:
        clave = equipo_desde_dict(e).clave
        for h in e.get("hallazgos", []):
            res[(clave, h["titulo"], h.get("puerto"))] = {**h, "equipo": e.get("nombre") or e.get("fabricante") or e.get("tipo", "")}
    for h in ((r.get("internet") or {}).get("hallazgos") or []):
        res[("internet", h["titulo"], h.get("puerto"))] = {**h, "equipo": "IP pública"}
    return res


def _salud(r: dict) -> dict:
    return r.get("salud") or salud.calcular(r)


def datos(cliente: str, red: str, mes: str, ruta_db: Path | None = None) -> dict:
    todas = [(i, f) for i, _c, f, rd, _n in visitas.listar(cliente, ruta_db) if rd == red]
    del_mes = [(i, f) for i, f in todas if f.startswith(mes)]
    if not del_mes:
        raise SinVisitas(f"No hay visitas de «{cliente or 'sin nombre'}» en la red {red} durante "
                         f"{_nombre_mes(mes)}.")
    previas = [(i, f) for i, f in todas if f < mes]
    base_id = previas[-1][0] if previas else del_mes[0][0]
    base, final = visitas.obtener(base_id, ruta_db), visitas.obtener(del_mes[-1][0], ruta_db)

    cambios = visitas.comparar(base, final) if base_id != del_mes[-1][0] else \
        {"nuevos": [], "faltan": [], "cambios": [], "desde": base["fecha"]}
    hb, hf = _hallazgos(base), _hallazgos(final)
    resueltos = [hb[k] for k in hb if k not in hf] if base_id != del_mes[-1][0] else []
    nuevos_h = [hf[k] for k in hf if k not in hb] if base_id != del_mes[-1][0] else []

    # Evolución: hasta 6 meses hacia atrás.
    desde = mes
    for _ in range(5):
        desde = _mes_anterior(desde)
    serie = []
    for i, f in todas:
        if desde <= f[:7] <= mes:
            serie.append((f, _salud(visitas.obtener(i, ruta_db))["puntaje"]))

    tipos: dict[str, int] = {}
    for e in final["equipos"]:
        tipos[e.get("tipo") or "Desconocido"] = tipos.get(e.get("tipo") or "Desconocido", 0) + 1

    return {
        "cliente": cliente, "red": red, "mes": mes, "visitas_mes": len(del_mes),
        "hay_base_previa": bool(previas), "base": base, "final": final,
        "salud_base": _salud(base), "salud_final": _salud(final),
        "cambios": cambios, "resueltos": resueltos, "nuevos_h": nuevos_h,
        "pendientes": sorted(hf.values(), key=lambda h: ("alto", "medio", "bajo", "info").index(h["nivel"])),
        "serie": serie, "tipos": dict(sorted(tipos.items(), key=lambda x: -x[1])),
    }


def resumen_ejecutivo(d: dict) -> str:
    sf, sb = d["salud_final"], d["salud_base"]
    partes = [f"Durante {_nombre_mes(d['mes'])} se hicieron {d['visitas_mes']} relevamiento"
              f"{'s' if d['visitas_mes'] > 1 else ''} de la red {d['red']}"
              + (f" ({d['cliente']})" if d["cliente"] else "") + "."]
    texto = f"La salud de la red quedó en {sf['puntaje']}/100 ({sf['estado'].lower()})"
    if d["hay_base_previa"]:
        dif = sf["puntaje"] - sb["puntaje"]
        texto += (f", {abs(dif)} punto{'s' if abs(dif) != 1 else ''} "
                  f"{'más' if dif > 0 else 'menos'} que en la visita anterior" if dif else
                  ", igual que en la visita anterior")
    partes.append(texto + ".")
    c = d["cambios"]
    equipos_final = len(d["final"]["equipos"])
    partes.append(f"Hay {equipos_final} equipos conectados"
                  + (f": aparecieron {len(c['nuevos'])} nuevos" if c["nuevos"] else "")
                  + (f"{' y' if c['nuevos'] else ':'} {len(c['faltan'])} dejaron de aparecer" if c["faltan"] else "")
                  + ".")
    pend = d["pendientes"]
    altos = sum(1 for h in pend if h["nivel"] == "alto")
    def problemas(n):
        return f"{n} problema{'s' if n != 1 else ''}"

    r, nu = len(d["resueltos"]), len(d["nuevos_h"])
    if r and nu:
        partes.append(f"Se resolvieron {problemas(r)} y surgieron {nu} nuevo{'s' if nu != 1 else ''}.")
    elif r:
        partes.append(f"Se resolvieron {problemas(r)} y no surgieron nuevos.")
    elif nu:
        partes.append(f"Surgieron {problemas(nu)} nuevo{'s' if nu != 1 else ''}.")
    if pend:
        graves = "" if not altos else (", 1 de ellos grave" if altos == 1 else f", {altos} de ellos graves")
        partes.append(f"Quedan {len(pend)} punto{'s' if len(pend) != 1 else ''} para revisar{graves}.")
    else:
        partes.append("No quedan puntos pendientes.")
    return " ".join(partes)


def _grafico(serie: list[tuple[str, int]]) -> str:
    if len(serie) < 2:
        return '<p class="nota">El gráfico de evolución aparece a partir de la segunda visita.</p>'
    ancho, alto, m = 900, 220, 40
    n = len(serie)
    xs = [m + i * (ancho - 2 * m) / (n - 1) for i in range(n)]
    ys = [alto - m - p / 100 * (alto - 2 * m) for _, p in serie]
    s = [f'<svg viewBox="0 0 {ancho} {alto}" xmlns="http://www.w3.org/2000/svg" role="img" '
         'aria-label="Evolución de la salud de la red" font-family="inherit">']
    for v, color in ((80, "#16a34a"), (60, "#ca8a04")):
        y = alto - m - v / 100 * (alto - 2 * m)
        s.append(f'<line x1="{m}" x2="{ancho - m}" y1="{y:.0f}" y2="{y:.0f}" stroke="{color}" '
                 f'stroke-dasharray="4 4" stroke-width="1" opacity=".6"/>'
                 f'<text x="{m - 6}" y="{y + 4:.0f}" text-anchor="end" font-size="10" fill="#64748b">{v}</text>')
    s.append('<polyline fill="none" stroke="#2563eb" stroke-width="2.5" points="'
             + " ".join(f"{x:.0f},{y:.0f}" for x, y in zip(xs, ys)) + '"/>')
    paso = max(1, n // 12)
    for i, ((f, p), x, y) in enumerate(zip(serie, xs, ys)):
        c = "#16a34a" if p >= 80 else "#ca8a04" if p >= 60 else "#dc2626"
        s.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="4.5" fill="{c}"><title>{_e(f[:10])}: {p}</title></circle>')
        if i % paso == 0 or i == n - 1:
            s.append(f'<text x="{x:.0f}" y="{y - 10:.0f}" text-anchor="middle" font-size="11" '
                     f'font-weight="600" fill="#0f172a">{p}</text>'
                     f'<text x="{x:.0f}" y="{alto - 14}" text-anchor="middle" font-size="10" fill="#64748b">'
                     f'{f[8:10]}/{f[5:7]}</text>')
    s.append("</svg>")
    return "".join(s)


def _lista_equipos(lista: list[dict]) -> str:
    return "<ul>" + "".join(
        f'<li><b class="mono">{_e(e["ip"])}</b> {_e(e.get("tipo", ""))} '
        f'<span class="gris">{_e(e.get("fabricante") or e.get("nombre") or "")}'
        f'{" · " + _e(e["mac"]) if e.get("mac") else ""}</span></li>' for e in lista) + "</ul>"


def _lista_hallazgos(lista: list[dict]) -> str:
    return "<ul>" + "".join(
        f'<li><span class="nivel" style="background:{NIVEL_COLOR[h["nivel"]]}">{NIVEL_TEXTO[h["nivel"]]}</span> '
        f'{_e(h["titulo"])} — <b class="mono">{_e(h["ip"])}</b> <span class="gris">{_e(h["equipo"])}'
        f'{" · " + _e(h["detalle"]) if h.get("detalle") else ""}</span></li>' for h in lista) + "</ul>"


def generar(d: dict) -> str:
    sf = d["salud_final"]
    titulo = f"Informe mensual · {_nombre_mes(d['mes']).capitalize()}"
    sub = f"Red {d['red']}" + (f" — {d['cliente']}" if d["cliente"] else "")
    dif = ""
    if d["hay_base_previa"]:
        n = sf["puntaje"] - d["salud_base"]["puntaje"]
        flecha, color = ("▲", "#16a34a") if n > 0 else ("▼", "#dc2626") if n < 0 else ("=", "#64748b")
        dif = f'<div style="color:{color};font-weight:600">{flecha} {abs(n)} respecto de la visita anterior</div>'
    c = d["cambios"]
    p = [f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(titulo)} · {_e(sub)} · Redportes</title><style>{CSS}
.resumen{{font-size:16px;background:#f8fafc;border-radius:10px;padding:14px 18px;border:1px solid #e2e8f0}}
.dos{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
@media (max-width:700px){{.dos{{grid-template-columns:1fr}}}}
</style></head><body>
<header><div><div class="marca">Redportes</div><h1>{_e(titulo)}</h1>
<div class="meta">{_e(sub)} · {d['visitas_mes']} visita{'s' if d['visitas_mes'] > 1 else ''} en el mes ·
última: {_e(datetime.fromisoformat(d['final']['fecha']).strftime('%d/%m/%Y %H:%M'))}</div></div>
<button class="no-print" onclick="window.print()">Guardar como PDF</button></header>
<section class="salud"><div class="nota-salud" style="border-color:{sf['color']};color:{sf['color']}">
<b>{sf['puntaje']}</b><span>/100</span></div><div><div class="salud-tit">Salud de la red:
<b style="color:{sf['color']}">{_e(sf['estado'])}</b></div>{dif}
<ul class="motivos">{''.join(f'<li>{_e(m)}</li>' for m in sf['motivos'])}</ul></div></section>
<section><h2>Resumen</h2><p class="resumen">{_e(resumen_ejecutivo(d))}</p></section>
<section><h2>Evolución de la salud</h2><div class="mapa">{_grafico(d['serie'])}</div></section>
<section class="dos"><div><h2>Equipos nuevos <span class="gris">({len(c['nuevos'])})</span></h2>
{_lista_equipos(c['nuevos']) if c['nuevos'] else '<p class="gris">Ninguno.</p>'}</div>
<div><h2>Dejaron de aparecer <span class="gris">({len(c['faltan'])})</span></h2>
{_lista_equipos(c['faltan']) if c['faltan'] else '<p class="gris">Ninguno.</p>'}</div></section>
<section class="dos"><div><h2>Problemas resueltos <span class="gris">({len(d['resueltos'])})</span></h2>
{_lista_hallazgos(d['resueltos']) if d['resueltos'] else '<p class="gris">Ninguno.</p>'}</div>
<div><h2>Problemas nuevos <span class="gris">({len(d['nuevos_h'])})</span></h2>
{_lista_hallazgos(d['nuevos_h']) if d['nuevos_h'] else '<p class="gris">Ninguno.</p>'}</div></section>
<section><h2>Pendientes <span class="gris">({len(d['pendientes'])})</span></h2>
{_lista_hallazgos(d['pendientes']) if d['pendientes'] else '<p>No quedan puntos pendientes.</p>'}</section>
<section><h2>Inventario por tipo</h2><div class="tabla"><table><thead><tr><th>Tipo de equipo</th>
<th>Cantidad</th></tr></thead><tbody>"""]
    p += [f"<tr><td>{_e(t)}</td><td>{n}</td></tr>" for t, n in d["tipos"].items()]
    p.append(f"""</tbody></table></div></section>
<footer><p class="firma">Generado con <a href="{SITIO}">Redportes</a> {__version__} · hecho por <a href="{AUTOR_URL}">{__autor__}</a></p><p>Generado el {datetime.now():%d/%m/%Y %H:%M}. Compara la última visita
del mes con la última visita anterior al mes.</p></footer></body></html>""")
    return "".join(p)


def nombre_archivo(cliente: str, red: str, mes: str) -> str:
    import re

    base = re.sub(r"[^\w.-]+", "_", cliente or "red").strip("_") or "red"
    return f"redportes_mensual_{base}_{red.split('/')[0]}_{mes}.html"
