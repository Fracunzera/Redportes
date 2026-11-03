"""Equipos que anuncian UPnP/SSDP en la red local (solo escucha respuestas a un M-SEARCH)."""

from __future__ import annotations

import socket
import time

_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: ssdp:all\r\n\r\n"
).encode()


def parsear_respuesta(datos: bytes) -> dict[str, str]:
    cab = {}
    for linea in datos.decode("utf-8", errors="replace").split("\r\n")[1:]:
        if ":" in linea:
            k, v = linea.split(":", 1)
            cab[k.strip().upper()] = v.strip()
    return cab


def buscar(ip_local: str = "", espera: float = 3.0) -> dict[str, list[str]]:
    """IP -> lista de tipos/servidores anunciados."""
    res: dict[str, set[str]] = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        if ip_local:
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip_local))
            except OSError:
                pass
        s.settimeout(0.5)
        for _ in range(2):
            s.sendto(_MSEARCH, ("239.255.255.250", 1900))
        fin = time.monotonic() + espera
        while time.monotonic() < fin:
            try:
                datos, (ip, _) = s.recvfrom(4096)
            except socket.timeout:
                continue
            cab = parsear_respuesta(datos)
            for clave in ("ST", "SERVER"):
                if cab.get(clave):
                    res.setdefault(ip, set()).add(cab[clave][:100])
    except OSError:
        pass
    finally:
        s.close()
    return {ip: sorted(v) for ip, v in res.items()}


def es_igd(anuncios: list[str]) -> bool:
    """El router permite que los equipos abran puertos hacia Internet solos."""
    return any("InternetGatewayDevice" in a or "WANIPConnection" in a or "WANPPPConnection" in a
               for a in anuncios)
