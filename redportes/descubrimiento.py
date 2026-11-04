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


def descubrir_con_nmap(red: str, limite: float = 120, parar=None) -> tuple[list[Equipo], str]:
    """(equipos, estado). -n: sin resolver nombres (lo hacemos aparte y es lo que más demoraba)."""
    from redportes.sistema import ejecutar_detallado

    salida, estado = ejecutar_detallado(["nmap", "-sn", "-n", "-T4", "--max-retries", "1", "-oX", "-", red],
                                        timeout=limite, cancelado=parar)
    return parsear_nmap_xml(salida), estado


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

def _mapa_cortable(func, items, workers, parar):
    """Como ex.map, pero deja de esperar apenas parar() es True. Devuelve pares (item, resultado)."""
    from concurrent.futures import FIRST_COMPLETED, wait as esperar

    ex = ThreadPoolExecutor(max_workers=workers)
    futuros = {ex.submit(func, it): it for it in items}
    pendientes = set(futuros)
    res = []
    try:
        while pendientes:
            hechos, pendientes = esperar(pendientes, timeout=0.3, return_when=FIRST_COMPLETED)
            for f in hechos:
                try:
                    res.append((futuros[f], f.result()))
                except Exception:  # noqa: BLE001
                    pass
            if parar and parar():
                break
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return res


def descubrir(red: str, usar_nmap: bool = True, progreso=lambda m: None, parar=lambda: False,
              avisar=lambda texto, recomendacion="": None) -> dict[str, Equipo]:
    redip = ipaddress.IPv4Network(red, strict=False)
    hosts = [str(h) for h in redip.hosts()]
    equipos: dict[str, Equipo] = {}

    def equipo(ip: str) -> Equipo:
        if ip not in equipos:
            equipos[ip] = Equipo(ip=ip)
        return equipos[ip]

    if usar_nmap and tiene("nmap"):
        limite = min(240, 30 + len(hosts) * 0.05)
        progreso("Buscando equipos con nmap…")
        encontrados, estado = descubrir_con_nmap(red, limite, parar)
        for e in encontrados:
            equipos[e.ip] = e
        if estado == "tiempo":
            avisar(f"nmap no terminó en {int(limite)} s: se siguió con la búsqueda propia de Redportes.",
                   "Revisá que Npcap esté instalado y actualizado (viene con nmap). Si en esta PC nmap "
                   "sigue trabándose, desactivalo en Herramientas → Usar nmap.")
        elif estado == "ok" and not encontrados:
            avisar("nmap no devolvió ningún equipo: se siguió con la búsqueda propia.",
                   "Puede faltar Npcap o permisos. Redportes funciona igual sin nmap.")
    if parar():
        return equipos

    from redportes import icmp

    progreso(f"Ping a {len(hosts)} direcciones…")
    respuestas = icmp.barrido(hosts, timeout=1.0, progreso=progreso, parar=parar)
    if respuestas is None and tiene("ping"):
        # Sin socket ICMP disponible: un proceso `ping` por dirección (lento en redes grandes).
        respuestas = {ip: r for ip, r in _mapa_cortable(hacer_ping, hosts, 128, parar) if r[0] is not None}
    respuestas = respuestas or {}
    for ip, (ttl, lat) in respuestas.items():
        e = equipo(ip)
        e.ttl, e.latencia_ms = ttl, round(lat, 1) if lat is not None else None
        e.marcar("ping")

    # Equipos que bloquean el ping (Windows con firewall, por ejemplo): un toque TCP.
    # Solo en redes chicas; en las grandes sería demasiado lento.
    sin_respuesta = [ip for ip in hosts if ip not in equipos]
    if sin_respuesta and len(hosts) <= TOQUE_TCP_MAX and not parar():
        progreso(f"Toque TCP a {len(sin_respuesta)} direcciones que no respondieron ping…")
        for ip, vivo in _mapa_cortable(toque_tcp, sin_respuesta, 256, parar):
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

    if not parar():
        progreso("Resolviendo nombres…")
        for ip, nombre in resolver_nombres(list(equipos)).items():
            if not equipos[ip].nombre:
                equipos[ip].nombre = nombre
    return equipos
