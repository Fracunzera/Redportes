"""Descubrimiento de equipos vivos en la red local.

Combina varias técnicas, todas pasivas o de "toque" (nada de credenciales):
- nmap -sn, si está instalado (con permisos de admin trae MAC y fabricante).
- ping a cada dirección (da TTL y latencia).
- sondeo TCP a puertos típicos: un "conexión rechazada" también delata un equipo vivo.
- la tabla ARP del sistema, que se llena sola con lo anterior y trae las MAC,
  incluso de equipos que bloquean el ping.
"""

from __future__ import annotations

import errno
import ipaddress
import re
import socket
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

from redportes.modelo import Equipo
from redportes.red import normalizar_mac
from redportes.sistema import ES_MAC, ES_WINDOWS, ejecutar, tiene

_IPV4 = r"(?:\d{1,3}\.){3}\d{1,3}"
_PUERTOS_TOQUE = (80, 443, 22, 445, 139, 3389, 554, 8080, 53, 8291)
TOQUE_TCP_MAX = 1024  # direcciones


# ---------------------------------------------------------------- ping

def comando_ping(ip: str) -> list[str]:
    if ES_WINDOWS:
        return ["ping", "-n", "1", "-w", "1000", ip]
    if ES_MAC:
        return ["ping", "-c", "1", "-t", "1", ip]
    return ["ping", "-c", "1", "-W", "1", ip]


def parsear_ping(texto: str) -> tuple[int | None, float | None]:
    """Devuelve (ttl, latencia_ms) de la salida de ping, o (None, None)."""
    ttl = re.search(r"ttl[=:]\s*(\d+)", texto, re.I)
    if not ttl:
        return None, None
    lat = re.search(r"(?:time|tiempo|tempo|zeit)\s*[=<]\s*([\d.,]+)\s*ms", texto, re.I)
    latencia = float(lat.group(1).replace(",", ".")) if lat else None
    return int(ttl.group(1)), latencia


def hacer_ping(ip: str) -> tuple[int | None, float | None]:
    return parsear_ping(ejecutar(comando_ping(ip), timeout=4))


# ---------------------------------------------------------------- toque TCP

def toque_tcp(ip: str, puertos=_PUERTOS_TOQUE, timeout: float = 0.4) -> bool:
    """True si algún puerto acepta o rechaza explícitamente la conexión."""
    for p in puertos:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            r = s.connect_ex((ip, p))
        except OSError:
            r = -1
        finally:
            s.close()
        if r == 0 or r in (errno.ECONNREFUSED, 10061):  # 10061 = WSAECONNREFUSED
            return True
    return False


# ---------------------------------------------------------------- ARP

def parsear_proc_arp(texto: str) -> dict[str, str]:
    res = {}
    for linea in texto.splitlines()[1:]:
        c = linea.split()
        if len(c) >= 4 and c[2] != "0x0":
            mac = normalizar_mac(c[3])
            if mac and mac != "00:00:00:00:00:00":
                res[c[0]] = mac
    return res


def parsear_arp_a(texto: str) -> dict[str, str]:
    """`arp -a` de Windows o `arp -an` de macOS/BSD."""
    res = {}
    for linea in texto.splitlines():
        m = re.search(rf"({_IPV4})\)?\s+(?:at\s+)?([0-9a-fA-F]{{1,2}}(?:[-:][0-9a-fA-F]{{1,2}}){{5}})", linea)
        if not m:
            continue
        partes = re.split(r"[-:]", m.group(2))
        mac = normalizar_mac("".join(p.zfill(2) for p in partes))
        if mac and mac not in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00") and not mac.startswith("01:00:5E"):
            res[m.group(1)] = mac
    return res


def tabla_arp() -> dict[str, str]:
    if ES_WINDOWS:
        return parsear_arp_a(ejecutar(["arp", "-a"]))
    if ES_MAC:
        return parsear_arp_a(ejecutar(["arp", "-an"]))
    try:
        return parsear_proc_arp(Path("/proc/net/arp").read_text())
    except OSError:
        return parsear_arp_a(ejecutar(["arp", "-an"]))


# ---------------------------------------------------------------- nmap

def parsear_nmap_xml(texto: str) -> list[Equipo]:
    equipos = []
    try:
        raiz = ET.fromstring(texto)
    except ET.ParseError:
        return equipos
    for host in raiz.findall("host"):
        estado = host.find("status")
        if estado is None or estado.get("state") != "up":
            continue
        eq = None
        mac, vendor = "", ""
        for a in host.findall("address"):
            if a.get("addrtype") == "ipv4":
                eq = Equipo(ip=a.get("addr"))
            elif a.get("addrtype") == "mac":
                mac = normalizar_mac(a.get("addr", ""))
                vendor = a.get("vendor", "")
        if eq is None:
            continue
        eq.mac, eq.fabricante = mac, vendor
        hn = host.find("hostnames/hostname")
        if hn is not None:
            eq.nombre = hn.get("name", "")
        eq.marcar("nmap")
        equipos.append(eq)
    return equipos


def descubrir_con_nmap(red: str) -> list[Equipo]:
    salida = ejecutar(["nmap", "-sn", "-T4", "-oX", "-", red], timeout=300)
    return parsear_nmap_xml(salida)


# ---------------------------------------------------------------- nombres

def resolver_nombres(ips: list[str], tiempo_max: float = 8) -> dict[str, str]:
    def uno(ip):
        try:
            return ip, socket.gethostbyaddr(ip)[0]
        except OSError:
            return ip, ""

    res = {}
    ex = ThreadPoolExecutor(max_workers=32)
    futuros = [ex.submit(uno, ip) for ip in ips]
    hechos, _ = wait(futuros, timeout=tiempo_max)
    for f in hechos:
        ip, nombre = f.result()
        if nombre and nombre != ip:
            res[ip] = nombre
    ex.shutdown(wait=False, cancel_futures=True)
    return res


# ---------------------------------------------------------------- todo junto

def descubrir(red: str, usar_nmap: bool = True, progreso=lambda m: None) -> dict[str, Equipo]:
    redip = ipaddress.IPv4Network(red, strict=False)
    hosts = [str(h) for h in redip.hosts()]
    equipos: dict[str, Equipo] = {}

    def equipo(ip: str) -> Equipo:
        if ip not in equipos:
            equipos[ip] = Equipo(ip=ip)
        return equipos[ip]

    if usar_nmap and tiene("nmap"):
        progreso("Buscando equipos con nmap…")
        for e in descubrir_con_nmap(red):
            equipos[e.ip] = e

    from redportes import icmp

    progreso(f"Ping a {len(hosts)} direcciones…")
    respuestas = icmp.barrido(hosts, timeout=1.0, progreso=progreso)
    if respuestas is None and tiene("ping"):
        # Sin socket ICMP disponible: un proceso `ping` por dirección (lento en redes grandes).
        with ThreadPoolExecutor(max_workers=128) as ex:
            respuestas = {ip: r for ip, r in zip(hosts, ex.map(hacer_ping, hosts)) if r[0] is not None}
    respuestas = respuestas or {}
    for ip, (ttl, lat) in respuestas.items():
        e = equipo(ip)
        e.ttl, e.latencia_ms = ttl, round(lat, 1) if lat is not None else None
        e.marcar("ping")

    # Equipos que bloquean el ping (Windows con firewall, por ejemplo): un toque TCP.
    # Solo en redes chicas; en las grandes sería demasiado lento.
    sin_respuesta = [ip for ip in hosts if ip not in equipos]
    if sin_respuesta and len(hosts) <= TOQUE_TCP_MAX:
        progreso(f"Toque TCP a {len(sin_respuesta)} direcciones que no respondieron ping…")
        with ThreadPoolExecutor(max_workers=256) as ex:
            for ip, vivo in zip(sin_respuesta, ex.map(toque_tcp, sin_respuesta)):
                if vivo:
                    equipo(ip).marcar("TCP")

    # La tabla ARP trae MACs y equipos que no contestan ping ni TCP.
    for ip, mac in tabla_arp().items():
        try:
            if ipaddress.IPv4Address(ip) not in redip:
                continue
        except ValueError:
            continue
        e = equipo(ip)
        if not e.mac:
            e.mac = mac
        e.marcar("ARP")

    progreso("Resolviendo nombres…")
    for ip, nombre in resolver_nombres(list(equipos)).items():
        if not equipos[ip].nombre:
            equipos[ip].nombre = nombre
    return equipos
