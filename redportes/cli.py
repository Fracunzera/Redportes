"""Línea de comandos de Redportes."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from redportes import __version__

NIVEL_ANSI = {"alto": "\033[31m", "medio": "\033[33m", "bajo": "\033[93m", "info": "\033[90m"}


def _color(texto: str, codigo: str) -> str:
    return f"{codigo}{texto}\033[0m" if sys.stdout.isatty() else texto


def _progreso(msg: str) -> None:
    print(_color("· ", "\033[34m") + msg, file=sys.stderr, flush=True)


def _nombre_archivo(cliente: str, red: str) -> str:
    from redportes.informe import nombre_archivo

    return nombre_archivo(cliente, red)


# ---------------------------------------------------------------- comandos

def cmd_interfaces(_args) -> int:
    from redportes.red import listar_interfaces, puerta_de_enlace

    gw = puerta_de_enlace()
    for i, itf in enumerate(listar_interfaces()):
        marca = " (principal)" if i == 0 else (" (virtual)" if itf.virtual else "")
        print(f"{itf.nombre:16} {itf.ip:15} {itf.red:18} {itf.mac or '':17}{marca}")
    print(f"\nPuerta de enlace: {gw or 'no encontrada'}")
    return 0


def cmd_escanear(args) -> int:
    from redportes import escaneo, informe, visitas
    from redportes.puertos import lista_de_puertos

    try:
        itf, red = escaneo.resolver_red(args.interfaz, args.red)
    except ValueError as e:
        print(f"{e} Mirá `redportes interfaces`.", file=sys.stderr)
        return 2
    try:
        lista = lista_de_puertos(args.puertos)
    except ValueError as e:
        print(f"Puertos inválidos: {e}", file=sys.stderr)
        return 2

    _progreso(f"Escaneando {red} desde {itf.nombre} ({itf.ip})")
    try:
        r = escaneo.ejecutar(itf, red, lista, cliente=args.cliente or "",
                             con_internet=args.internet, usar_nmap=not args.sin_nmap,
                             forzar=args.forzar, progreso=_progreso)
    except escaneo.RedDemasiadoGrande as e:
        print(str(e), file=sys.stderr)
        return 2

    cambios = None
    if not args.no_guardar:
        previo = visitas.anterior(r["cliente"], r["red"])
        id_visita = visitas.guardar(r)
        if previo:
            cambios = visitas.comparar(previo, r)
        _progreso(f"Visita guardada (n.º {id_visita}).")

    _resumen(r, cambios)

    destino = Path(args.salida or _nombre_archivo(r["cliente"], r["red"]))
    destino.write_text(informe.generar(r, cambios), encoding="utf-8")
    print(f"\nInforme: {destino.resolve()}")
    if args.json:
        Path(args.json).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON:    {Path(args.json).resolve()}")
    if args.abrir:
        webbrowser.open(destino.resolve().as_uri())
    return 0


def _resumen(r: dict, cambios: dict | None) -> None:
    from redportes.escaneo import todos_los_hallazgos

    print()
    print(f"{'IP':15} {'TIPO':28} {'FABRICANTE':24} PUERTOS")
    for e in r["equipos"]:
        puertos = ",".join(str(p["numero"]) for p in e["puertos"])
        marca = "★" if e["es_este_equipo"] else ("GW" if e["es_puerta"] else "")
        print(f"{e['ip']:15} {(e['tipo'] + ' ' + marca)[:28]:28} {(e['fabricante'] or '')[:24]:24} {puertos}")
    hall = todos_los_hallazgos(r)
    if hall:
        print(f"\nPara revisar ({len(hall)}):")
        for h in hall:
            print(f"  {_color(f'{h.nivel.upper():<6}', NIVEL_ANSI[h.nivel])} {h.ip:15} {h.titulo}")
    w = r.get("wan") or {}
    if w.get("texto"):
        print(f"\nWAN del router: {w['texto']}")
    if r.get("internet"):
        print("\nSalida a Internet:")
        for c in r["internet"]["conclusiones"]:
            print(f"  - {c}")
        if r["internet"].get("exposicion"):
            print(f"  - Desde Internet (Shodan): {r['internet']['exposicion']}")
    if cambios:
        print(f"\nDesde la visita anterior: {len(cambios['nuevos'])} nuevos, "
              f"{len(cambios['faltan'])} ya no están, {len(cambios['cambios'])} cambiaron.")


def cmd_visitas(args) -> int:
    from redportes import visitas

    filas = visitas.listar(args.cliente)
    if not filas:
        print("Todavía no hay visitas guardadas.")
        return 0
    print(f"{'N.º':>4}  {'FECHA':19}  {'CLIENTE':24} {'RED':18} EQUIPOS")
    for i, cliente, fecha, red, n in filas:
        print(f"{i:>4}  {fecha:19}  {(cliente or '—')[:24]:24} {red:18} {n}")
    return 0


def cmd_informe(args) -> int:
    from redportes import informe, visitas

    r = visitas.obtener(args.id)
    if not r:
        print(f"No existe la visita {args.id}.", file=sys.stderr)
        return 2
    previo = visitas.anterior(r["cliente"], r["red"], antes_de=args.id)
    cambios = visitas.comparar(previo, r) if previo else None
    destino = Path(args.salida or _nombre_archivo(r["cliente"], r["red"]))
    destino.write_text(informe.generar(r, cambios), encoding="utf-8")
    print(f"Informe: {destino.resolve()}")
    if args.abrir:
        webbrowser.open(destino.resolve().as_uri())
    return 0


def cmd_actualizar_oui(_args) -> int:
    from redportes import oui

    print(f"Bajando la base de fabricantes de {oui.URL_IEEE} …")
    try:
        n = oui.actualizar_base()
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo bajar: {e}", file=sys.stderr)
        return 1
    print(f"Listo: {n} fabricantes.")
    return 0


# ---------------------------------------------------------------- argumentos

def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="redportes",
        description="Escáner de red local para técnicos: qué hay conectado, qué conviene revisar "
                    "y un informe listo para PDF.")
    p.add_argument("--version", action="version", version=f"redportes {__version__}")
    sub = p.add_subparsers(dest="comando")

    e = sub.add_parser("escanear", help="escanea la red y genera el informe (comando por defecto)")
    e.add_argument("-r", "--red", help="red a escanear, ej. 192.168.1.0/24 (por defecto la de la interfaz principal)")
    e.add_argument("-i", "--interfaz", help="interfaz a usar (ver `redportes interfaces`)")
    e.add_argument("-p", "--puertos", default="rapido",
                   help="rapido (21 puertos), completo, ninguno o lista: 22,80,8000-8010")
    e.add_argument("-c", "--cliente", help="nombre del cliente o sitio, para el historial de visitas")
    e.add_argument("--internet", action="store_true",
                   help="analiza la salida a Internet (traceroute, IP pública): genera tráfico hacia afuera")
    e.add_argument("-o", "--salida", help="archivo HTML del informe")
    e.add_argument("--json", help="guarda también el resultado crudo en JSON")
    e.add_argument("--abrir", action="store_true", help="abre el informe en el navegador al terminar")
    e.add_argument("--sin-nmap", action="store_true", help="no usar nmap aunque esté instalado")
    e.add_argument("--no-guardar", action="store_true", help="no guardar la visita en el historial")
    e.add_argument("--forzar", action="store_true", help="permite redes más grandes que una /16")
    e.set_defaults(func=cmd_escanear)

    sub.add_parser("interfaces", help="muestra las interfaces y la puerta de enlace").set_defaults(func=cmd_interfaces)

    v = sub.add_parser("visitas", help="lista las visitas guardadas")
    v.add_argument("-c", "--cliente")
    v.set_defaults(func=cmd_visitas)

    inf = sub.add_parser("informe", help="regenera el informe de una visita guardada")
    inf.add_argument("id", type=int)
    inf.add_argument("-o", "--salida")
    inf.add_argument("--abrir", action="store_true")
    inf.set_defaults(func=cmd_informe)

    sub.add_parser("actualizar-oui", help="baja la base completa de fabricantes de la IEEE"
                   ).set_defaults(func=cmd_actualizar_oui)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = construir_parser()
    comandos = {"escanear", "interfaces", "visitas", "informe", "actualizar-oui"}
    if not argv or (argv[0] not in comandos and argv[0] not in ("-h", "--help", "--version")):
        argv = ["escanear"] + argv
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        return 130
