"""Orquesta un escaneo completo y devuelve un resultado serializable."""

from __future__ import annotations

import ipaddress
import socket
from datetime import datetime

from redportes import __version__, clasificacion, descubrimiento, hallazgos, oui, puertos, upnp
from redportes.modelo import Equipo, a_dict
from redportes.red import Interfaz, puerta_de_enlace, servidores_dns
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
             forzar: bool = False, progreso=lambda m: None) -> dict:
    redip = ipaddress.IPv4Network(red, strict=False)
    if redip.num_addresses > MAX_HOSTS and not forzar:
        raise RedDemasiadoGrande(
            f"La red {redip} tiene {redip.num_addresses:,} direcciones (el ping solo tardaría unos "
            f"{tiempo_estimado(redip.num_addresses) / 60:.0f} minutos). Usá --forzar si de verdad "
            f"querés escanearla entera, o pasá una red más chica con --red.".replace(",", "."))

    inicio = datetime.now()
    puerta = puerta_de_enlace()
    equipos = descubrimiento.descubrir(str(redip), usar_nmap=usar_nmap, progreso=progreso)

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

    res_puertos = puertos.escanear(sorted(equipos, key=_orden_ip), lista_puertos, progreso)
    for ip, lista in res_puertos.items():
        equipos[ip].puertos = lista

    smb = [e for e in equipos.values() if 445 in e.abiertos()]
    if smb:
        progreso("Revisando SMBv1…")
        for e in smb:
            e.smbv1 = puertos.acepta_smbv1(e.ip)

    progreso("Escuchando anuncios UPnP…")
    anuncios_upnp, igd = upnp.buscar(interfaz.ip)
    for ip, anuncios in anuncios_upnp.items():
        if ip in equipos:
            equipos[ip].upnp = anuncios

    progreso("Preguntándole al router su IP WAN…")
    from redportes import wan

    ubicaciones = igd.get(puerta, []) + [u for ip, lista in igd.items() if ip != puerta for u in lista]
    datos_wan = wan.ip_wan(puerta, ubicaciones)

    for e in equipos.values():
        clasificacion.clasificar(e)
        e.hallazgos = hallazgos.evaluar(e, str(redip))

    salida = None
    if con_internet:
        progreso("Analizando la salida a Internet…")
        from redportes import internet

        salida = internet.revisar(puerta, cgnat_wan=datos_wan.get("tipo") == "cgnat")

    from redportes.internet import describir_dns

    lista = sorted(equipos.values(), key=lambda e: _orden_ip(e.ip))
    r = {
        "version": __version__,
        "cliente": cliente,
        "fecha": inicio.isoformat(timespec="seconds"),
        "duracion_s": round((datetime.now() - inicio).total_seconds(), 1),
        "red": str(redip),
        "interfaz": a_dict(interfaz),
        "puerta": puerta,
        "dns": describir_dns(servidores_dns(), puerta),
        "wan": datos_wan,
        "sistema": SO,
        "admin": es_admin(),
        "nmap": usar_nmap and tiene("nmap"),
        "puertos_revisados": lista_puertos,
        "internet": salida,
        "equipos": [a_dict(e) for e in lista],
    }
    from redportes import salud

    r["salud"] = salud.calcular(r)
    return r


def _orden_ip(ip: str) -> int:
    return int(ipaddress.IPv4Address(ip))


def todos_los_hallazgos(resultado: dict) -> list:
    from redportes.modelo import Hallazgo

    lista = [Hallazgo(**h) for e in resultado["equipos"] for h in e.get("hallazgos", [])]
    lista += [Hallazgo(**h) for h in ((resultado.get("internet") or {}).get("hallazgos") or [])]
    return hallazgos.ordenar(lista)
