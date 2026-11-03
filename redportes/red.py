"""Datos de la red local: interfaces, puerta de enlace y DNS."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path

import psutil

from redportes.sistema import ES_MAC, ES_WINDOWS, ejecutar

_IPV4 = r"(?:\d{1,3}\.){3}\d{1,3}"

# Nombres típicos de interfaces virtuales que no suelen ser "la red del cliente".
_VIRTUALES = ("lo", "docker", "veth", "br-", "virbr", "vmnet", "vboxnet", "tun", "tap",
              "wg", "zt", "tailscale", "utun", "vEthernet", "Loopback", "isatap")


@dataclass
class Interfaz:
    nombre: str
    ip: str
    mascara: str
    red: str
    mac: str = ""
    virtual: bool = False

    @property
    def red_ip(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(self.red, strict=False)


def ip_de_salida() -> str:
    """IP local que el sistema usaría para salir (no envía ningún paquete)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # TEST-NET-1: un UDP connect no transmite nada
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def listar_interfaces() -> list[Interfaz]:
    """Interfaces IPv4 activas, con la de salida primero."""
    estados = psutil.net_if_stats()
    salida = ip_de_salida()
    res: list[Interfaz] = []
    for nombre, direcciones in psutil.net_if_addrs().items():
        if nombre in estados and not estados[nombre].isup:
            continue
        mac = ""
        for d in direcciones:
            if d.family == psutil.AF_LINK and d.address:
                mac = normalizar_mac(d.address)
        for d in direcciones:
            if d.family != socket.AF_INET or not d.netmask:
                continue
            ip = ipaddress.IPv4Address(d.address)
            if ip.is_loopback or ip.is_link_local:
                continue
            red = ipaddress.IPv4Network(f"{d.address}/{d.netmask}", strict=False)
            res.append(Interfaz(
                nombre=nombre, ip=d.address, mascara=d.netmask, red=str(red), mac=mac,
                virtual=nombre.startswith(_VIRTUALES),
            ))
    res.sort(key=lambda i: (i.ip != salida, i.virtual, i.nombre))
    return res


def normalizar_mac(mac: str) -> str:
    limpio = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(limpio) != 12:
        return ""
    return ":".join(limpio[i:i + 2] for i in range(0, 12, 2)).upper()


# ---------------------------------------------------------------- gateway

def parsear_proc_route(texto: str) -> str:
    for linea in texto.splitlines()[1:]:
        campos = linea.split()
        if len(campos) >= 3 and campos[1] == "00000000":
            gw = int(campos[2], 16)
            if gw:
                return socket.inet_ntoa(gw.to_bytes(4, "little"))
    return ""


def parsear_route_print(texto: str) -> str:
    """Salida de `route print -4` de Windows (cualquier idioma)."""
    for linea in texto.splitlines():
        m = re.match(rf"\s*0\.0\.0\.0\s+0\.0\.0\.0\s+({_IPV4})\s", linea)
        if m:
            return m.group(1)
    return ""


def puerta_de_enlace() -> str:
    if ES_WINDOWS:
        return parsear_route_print(ejecutar(["route", "print", "-4"]))
    if ES_MAC:
        m = re.search(rf"gateway:\s*({_IPV4})", ejecutar(["route", "-n", "get", "default"]))
        return m.group(1) if m else ""
    try:
        return parsear_proc_route(Path("/proc/net/route").read_text())
    except OSError:
        return ""


# ---------------------------------------------------------------- DNS

def parsear_resolv_conf(texto: str) -> list[str]:
    return re.findall(rf"^\s*nameserver\s+({_IPV4})", texto, re.M)


def parsear_ipconfig_dns(texto: str) -> list[str]:
    """Servidores DNS de `ipconfig /all` (inglés o castellano)."""
    res: list[str] = []
    en_dns = False
    for linea in texto.splitlines():
        if "DNS" in linea and ":" in linea and re.search(r"(Servers|Servidores)", linea):
            en_dns = True
            res += re.findall(_IPV4, linea.split(":", 1)[1])
        elif en_dns and re.fullmatch(rf"\s+{_IPV4}\s*", linea):
            res.append(linea.strip())
        else:
            en_dns = False
    return list(dict.fromkeys(res))


def servidores_dns() -> list[str]:
    if ES_WINDOWS:
        return parsear_ipconfig_dns(ejecutar(["ipconfig", "/all"]))
    try:
        servidores = parsear_resolv_conf(Path("/etc/resolv.conf").read_text())
    except OSError:
        servidores = []
    # systemd-resolved: el resolv.conf apunta a 127.0.0.53, preguntamos los reales.
    if servidores and all(s.startswith("127.") for s in servidores):
        reales = re.findall(_IPV4, ejecutar(["resolvectl", "dns"]))
        if reales:
            return list(dict.fromkeys(reales))
    return servidores


def es_privada(ip: str) -> bool:
    try:
        return ipaddress.IPv4Address(ip) in ipaddress.IPv4Network("10.0.0.0/8") or \
            ipaddress.IPv4Address(ip) in ipaddress.IPv4Network("172.16.0.0/12") or \
            ipaddress.IPv4Address(ip) in ipaddress.IPv4Network("192.168.0.0/16")
    except ValueError:
        return False


def es_cgnat(ip: str) -> bool:
    try:
        return ipaddress.IPv4Address(ip) in ipaddress.IPv4Network("100.64.0.0/10")
    except ValueError:
        return False
