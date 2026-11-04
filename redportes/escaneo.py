"""Orquesta un escaneo completo y devuelve un resultado serializable."""

from __future__ import annotations

import ipaddress
import socket
from datetime import datetime

from redportes import __version__, clasificacion, descubrimiento, hallazgos, oui, puertos, upnp
from redportes.modelo import Equipo, a_dict
from redportes.red import Interfaz, puerta_de_enlace, servidores_dns
from redportes.control import Control
from redportes.icmp import tiempo_estimado
from redportes.sistema import SO, es_admin, tiene

MAX_HOSTS = 65536  # una /16; más grande requiere confirmación


class RedDemasiadoGrande(ValueError):
    pass


def resolver_red(nombre_interfaz: str | None = None, red: str | None = None) -> tuple[Interfaz, str]:
    """Elige interfaz y red a escanear. Lanza ValueError con un mensaje para el usuario."""
    from redportes.red import listar_interfaces

    todas = listar_interfaces()
    candidatas = [i for i in todas if i.nombre == nombre_interfaz] if nombre_interfaz else todas
    if not candidatas:
        raise ValueError(f"No encontré la interfaz {nombre_interfaz}." if nombre_interfaz
                         else "No hay ninguna interfaz IPv4 activa.")
    itf = candidatas[0]
    if not red:
        return itf, itf.red
    try:
        redip = ipaddress.IPv4Network(red.strip(), strict=False)
    except ValueError:
        raise ValueError(f"Red inválida: {red} (ejemplo: 192.168.1.0/24)") from None
    for i in todas:  # si la red pedida pertenece a otra interfaz, usamos esa
        if ipaddress.IPv4Address(i.ip) in redip:
            itf = i
            break
    return itf, str(redip)


def ejecutar(interfaz: Interfaz, red: str, lista_puertos: list[int], cliente: str = "",
             con_internet: bool = False, usar_nmap: bool = True,
             forzar: bool = False, progreso=lambda m: None, control: Control | None = None) -> dict:
    """Escaneo completo. Con `control` se puede detener (lanza control.Cancelado) y cada etapa
    tiene un tiempo máximo: si se pasa, sigue con lo demás y deja un aviso en el resultado."""
    redip = ipaddress.IPv4Network(red, strict=False)
    if redip.num_addresses > MAX_HOSTS and not forzar:
        raise RedDemasiadoGrande(
            f"La red {redip} tiene {redip.num_addresses:,} direcciones (el ping solo tardaría unos "
            f"{tiempo_estimado(redip.num_addresses) / 60:.0f} minutos). Usá --forzar si de verdad "
            f"querés escanearla entera, o pasá una red más chica con --red.".replace(",", "."))
    ctl = control or Control(progreso)
    n = redip.num_addresses

    inicio = datetime.now()
    puerta = puerta_de_enlace()
    limite = 90 + min(240, 30 + n * 0.05) + tiempo_estimado(n) * 2 + (40 if n <= 1024 else 0)
    equipos = ctl.etapa(
        "Buscando equipos",
        lambda parar: descubrimiento.descubrir(str(redip), usar_nmap, ctl.progreso, parar, ctl.avisar),
        limite,
        al_vencer=lambda t: ctl.avisar(f"La búsqueda de equipos se cortó a los {int(t)} s.",
                                       "Puede faltar algún equipo. Probá de nuevo o escaneá una red más chica.")
    ) or {}

    # Este equipo siempre está, aunque no se responda a sí mismo por ARP.
    if ipaddress.IPv4Address(interfaz.ip) in redip:
        yo = equipos.setdefault(interfaz.ip, Equipo(ip=interfaz.ip))
        yo.es_este_equipo = True
        yo.mac = yo.mac or interfaz.mac
        yo.nombre = yo.nombre or socket.gethostname()
        yo.marcar("local")
    if puerta in equipos:
        equipos[puerta].es_puerta = True

    for e in equipos.values():
        if e.mac and not e.fabricante:
            e.fabricante = oui.fabricante(e.mac)

    ips = sorted(equipos, key=_orden_ip)
    pares = len(ips) * len(lista_puertos)
    res_puertos = ctl.etapa(
        "Revisando puertos",
        lambda parar: puertos.escanear(ips, lista_puertos, ctl.progreso, parar, ctl.avisar),
        60 + pares * 0.8 / 400 * 2 + 60,
    ) or {}
    for ip, lista in res_puertos.items():
        equipos[ip].puertos = lista

    smb = [e for e in equipos.values() if 445 in e.abiertos()]
    if smb:
        def revisar_smb(parar):
            for e in smb:
                if parar():
                    break
                e.smbv1 = puertos.acepta_smbv1(e.ip)

        ctl.etapa("Revisando SMBv1", revisar_smb, 15 + 4 * len(smb))

    anuncios_upnp, igd = ctl.etapa("Escuchando anuncios UPnP", lambda parar: upnp.buscar(interfaz.ip), 10) \
        or ({}, {})
    for ip, anuncios in anuncios_upnp.items():
        if ip in equipos:
            equipos[ip].upnp = anuncios

    for e in equipos.values():
        clasificacion.clasificar(e)
        e.hallazgos = hallazgos.evaluar(e, str(redip))

    inet = parte_internet(ctl, puerta, igd, con_internet)

    lista = sorted(equipos.values(), key=lambda e: _orden_ip(e.ip))
    r = {
        "version": __version__,
        "cliente": cliente,
        "fecha": inicio.isoformat(timespec="seconds"),
        "duracion_s": 0,
        "red": str(redip),
        "interfaz": a_dict(interfaz),
        "puerta": puerta,
        **inet,
        "equipo_local": ctl.etapa("Leyendo la configuración de este equipo", lambda parar: _equipo_local(), 20),
        "sistema": SO,
        "admin": es_admin(),
        "nmap": usar_nmap and tiene("nmap"),
        "puertos_revisados": lista_puertos,
        "equipos": [a_dict(e) for e in lista],
        "avisos": ctl.avisos,
    }
    r["duracion_s"] = round((datetime.now() - inicio).total_seconds(), 1)
    from redportes import salud

    r["salud"] = salud.calcular(r)
    return r


def parte_internet(ctl: Control, puerta: str, igd: dict | None, con_internet: bool) -> dict:
    """IP WAN del router y, si se pide, salida a Internet y prueba de conexión."""
    from redportes import config, wan
    from redportes.internet import describir_dns

    if igd is None:
        _, igd = ctl.etapa("Buscando el router por UPnP", lambda parar: upnp.buscar(), 10) or ({}, {})
    ubicaciones = igd.get(puerta, []) + [u for ip, lista in igd.items() if ip != puerta for u in lista]
    datos_wan = ctl.etapa("Preguntándole al router su IP WAN", lambda parar: wan.ip_wan(puerta, ubicaciones), 20) \
        or wan.describir("", "")

    salida, diag = None, None
    if con_internet:
        from redportes import diagnostico, internet

        urls = [u for u in [config.leer().get("url_proveedor")] if u]
        salida = ctl.etapa(
            "Analizando la salida a Internet",
            lambda parar: internet.revisar(puerta, cgnat_wan=datos_wan.get("tipo") == "cgnat",
                                           urls_proveedor=urls, parar=parar),
            180,
            al_vencer=lambda t: ctl.avisar(f"El análisis de la salida a Internet se cortó a los {int(t)} s.",
                                           "El traceroute o algún servicio externo no respondió. Probá con "
                                           "«Probar solo Internet» más tarde."))
        diag = ctl.etapa("Probando la conexión (ping, DNS, navegación)", lambda parar: diagnostico.ejecutar(), 60,
                         al_vencer=lambda t: ctl.avisar("La prueba de conexión no terminó a tiempo.",
                                                        "Usá la pestaña Diagnóstico para repetirla."))
        if salida and salida.get("proveedor") and not datos_wan.get("ip"):
            prov = salida["proveedor"]
            datos_wan = wan.describir(prov["ip"], f"speedtest de {prov['proveedor']}")
    return {"wan": datos_wan, "internet": salida, "diagnostico": diag,
            "dns": describir_dns(servidores_dns(), puerta)}


def solo_internet(progreso=lambda m: None, control: Control | None = None) -> dict:
    """Solo la parte de Internet, sin escanear la red local."""
    ctl = control or Control(progreso)
    inicio = datetime.now()
    puerta = puerta_de_enlace()
    r = {"version": __version__, "fecha": inicio.isoformat(timespec="seconds"), "puerta": puerta,
         **parte_internet(ctl, puerta, None, True), "avisos": ctl.avisos}
    r["duracion_s"] = round((datetime.now() - inicio).total_seconds(), 1)
    return r


def texto_internet(r: dict) -> str:
    """Resumen de la parte de Internet para la pantalla o para copiar."""
    lineas = []
    w = r.get("wan") or {}
    if w.get("ip"):
        from redportes.wan import origen

        lineas.append(f"IP WAN del router: {w['ip']} ({origen(w)})")
    if w.get("texto"):
        lineas += [w["texto"], ""]
    inet = r.get("internet")
    if inet:
        if inet.get("ip_publica"):
            lineas.append(f"IP pública: {inet['ip_publica']}")
        lineas += [f"• {c}" for c in inet.get("conclusiones", [])]
        if inet.get("exposicion"):
            lineas.append(f"Qué se ve desde Internet (Shodan): {inet['exposicion']}")
        if inet.get("saltos"):
            lineas += ["", "Saltos:"]
            for s in inet["saltos"]:
                ms = f"{s['ms']:.0f} ms" if s.get("ms") is not None else ""
                lineas.append(f"  {s['n']:>2}  {s['ip'] or '*':16} {s.get('tipo', ''):14} {ms}")
    dg = r.get("diagnostico")
    if dg:
        lineas += ["", "Prueba de conexión:"] + [f"• {c}" for c in dg.get("conclusiones", [])]
    if r.get("dns"):
        lineas += ["", "DNS: " + ", ".join(f"{d['ip']} ({d['quien']})" for d in r["dns"])]
    for a in r.get("avisos") or []:
        lineas += ["", f"⚠ {a['texto']}" + (f" {a['recomendacion']}" if a.get("recomendacion") else "")]
    return "\n".join(lineas)


def _equipo_local() -> dict | None:
    try:
        from redportes import equipo_local

        return equipo_local.recolectar()
    except Exception:  # noqa: BLE001 — nunca debe frenar el escaneo
        return None


def _orden_ip(ip: str) -> int:
    return int(ipaddress.IPv4Address(ip))


def todos_los_hallazgos(resultado: dict) -> list:
    from redportes.modelo import Hallazgo

    lista = [Hallazgo(**h) for e in resultado["equipos"] for h in e.get("hallazgos", [])]
    lista += [Hallazgo(**h) for h in ((resultado.get("internet") or {}).get("hallazgos") or [])]
    return hallazgos.ordenar(lista)
