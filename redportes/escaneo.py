"""Orquesta un escaneo completo y devuelve un resultado serializable."""

from __future__ import annotations

import ipaddress
import socket
from datetime import datetime

from redportes import __version__, clasificacion, descubrimiento, hallazgos, oui, puertos, upnp
from redportes.modelo import Equipo, a_dict
from redportes.red import Interfaz, puerta_de_enlace, servidores_dns
from redportes.sistema import SO, es_admin, tiene

MAX_HOSTS = 1024


class RedDemasiadoGrande(ValueError):
    pass


def ejecutar(interfaz: Interfaz, red: str, lista_puertos: list[int], cliente: str = "",
             con_internet: bool = False, usar_nmap: bool = True,
             forzar: bool = False, progreso=lambda m: None) -> dict:
    redip = ipaddress.IPv4Network(red, strict=False)
    if redip.num_addresses > MAX_HOSTS and not forzar:
        raise RedDemasiadoGrande(
            f"La red {redip} tiene {redip.num_addresses} direcciones. Usá --forzar si de verdad "
            f"querés escanearla entera, o pasá una red más chica con --red.")

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
    for ip, anuncios in upnp.buscar(interfaz.ip).items():
        if ip in equipos:
            equipos[ip].upnp = anuncios

    for e in equipos.values():
        clasificacion.clasificar(e)
        e.hallazgos = hallazgos.evaluar(e)

    salida = None
    if con_internet:
        progreso("Analizando la salida a Internet…")
        from redportes import internet

        salida = internet.revisar(puerta)

    from redportes.internet import describir_dns

    lista = sorted(equipos.values(), key=lambda e: _orden_ip(e.ip))
    return {
        "version": __version__,
        "cliente": cliente,
        "fecha": inicio.isoformat(timespec="seconds"),
        "duracion_s": round((datetime.now() - inicio).total_seconds(), 1),
        "red": str(redip),
        "interfaz": a_dict(interfaz),
        "puerta": puerta,
        "dns": describir_dns(servidores_dns(), puerta),
        "sistema": SO,
        "admin": es_admin(),
        "nmap": usar_nmap and tiene("nmap"),
        "puertos_revisados": lista_puertos,
        "internet": salida,
        "equipos": [a_dict(e) for e in lista],
    }


def _orden_ip(ip: str) -> int:
    return int(ipaddress.IPv4Address(ip))


def todos_los_hallazgos(resultado: dict) -> list:
    from redportes.modelo import Hallazgo

    lista = [Hallazgo(**h) for e in resultado["equipos"] for h in e.get("hallazgos", [])]
    return hallazgos.ordenar(lista)
