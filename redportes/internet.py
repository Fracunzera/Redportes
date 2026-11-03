"""Cómo sale la red a Internet: saltos, doble NAT, CGNAT y DNS.

Solo se ejecuta si el usuario lo pide (`--internet`), porque implica tráfico hacia afuera.
"""

from __future__ import annotations

import ipaddress
import json
import re
import urllib.request

from redportes.red import es_cgnat, es_privada
from redportes.sistema import ES_WINDOWS, ejecutar, tiene

DESTINO = "8.8.8.8"
_IPV4 = r"(?:\d{1,3}\.){3}\d{1,3}"

DNS_CONOCIDOS = {
    "8.8.8.8": "Google", "8.8.4.4": "Google",
    "1.1.1.1": "Cloudflare", "1.0.0.1": "Cloudflare",
    "9.9.9.9": "Quad9", "149.112.112.112": "Quad9",
    "208.67.222.222": "OpenDNS", "208.67.220.220": "OpenDNS",
}


def comando_traza() -> list[str] | None:
    if ES_WINDOWS:
        return ["tracert", "-d", "-h", "10", "-w", "800", DESTINO]
    if tiene("traceroute"):
        return ["traceroute", "-n", "-q", "1", "-w", "1", "-m", "10", DESTINO]
    if tiene("tracepath"):
        return ["tracepath", "-n", "-m", "10", DESTINO]
    return None


def parsear_traza(texto: str) -> list[dict]:
    """Funciona con traceroute, tracepath y tracert (inglés o castellano)."""
    saltos: dict[int, dict] = {}
    for linea in texto.splitlines():
        m = re.match(r"^\s*(\d+)\??:?\s+(.*)$", linea)
        if not m:
            continue
        n, resto = int(m.group(1)), m.group(2)
        if n in saltos and saltos[n]["ip"]:
            continue
        ips = re.findall(_IPV4, resto)
        ms = re.search(r"<?\s*([\d.]+)\s*ms", resto)
        saltos[n] = {
            "n": n,
            "ip": ips[-1] if ips else "",
            "ms": float(ms.group(1)) if ms and ips else None,
        }
    return [saltos[k] for k in sorted(saltos)]


def tipo_ip(ip: str) -> str:
    if not ip:
        return "sin respuesta"
    if es_cgnat(ip):
        return "cgnat"
    if es_privada(ip):
        return "privada"
    try:
        if ipaddress.IPv4Address(ip).is_global:
            return "publica"
    except ValueError:
        pass
    return "otra"


def analizar_saltos(saltos: list[dict], puerta: str) -> dict:
    """Saca conclusiones de la traza: doble NAT, CGNAT y dónde empieza Internet."""
    for s in saltos:
        s["tipo"] = tipo_ip(s["ip"])
        s["es_puerta"] = bool(puerta) and s["ip"] == puerta

    primer_publico = next((i for i, s in enumerate(saltos) if s["tipo"] == "publica"), None)
    antes = saltos[:primer_publico] if primer_publico is not None else saltos
    privados = [s for s in antes if s["tipo"] == "privada"]
    cgnat = [s for s in antes if s["tipo"] == "cgnat"]

    conclusiones = []
    doble_nat = False
    if len(privados) >= 2 and saltos and saltos[0]["tipo"] == "privada" and len(saltos) > 1 \
            and saltos[1]["tipo"] == "privada":
        doble_nat = True
        conclusiones.append(
            f"Doble NAT: el router ({saltos[0]['ip']}) sale por otro equipo que también traduce "
            f"({saltos[1]['ip']}). Puede ser un segundo router del cliente o el módem del operador. "
            "Complica abrir puertos, VPNs y algunas llamadas de VoIP. Si el segundo equipo es el "
            "módem del operador, conviene ponerlo en modo bridge."
        )
    if cgnat:
        conclusiones.append(
            f"CGNAT: aparece una dirección del rango 100.64.0.0/10 ({cgnat[0]['ip']}). El operador "
            "comparte la IP pública entre varios clientes: no se pueden abrir puertos desde afuera. "
            "Para acceso remoto hay que pedir IP pública al operador o usar una VPN saliente "
            "(WireGuard contra un servidor con IP pública)."
        )
    if primer_publico is None and saltos:
        conclusiones.append("La traza no llegó a ninguna dirección pública: puede haber "
                            "un firewall que bloquea el traceroute.")
    if not conclusiones and saltos:
        conclusiones.append("Salida directa: un solo nivel de NAT, sin CGNAT detectado.")
    return {"saltos": saltos, "doble_nat": doble_nat, "cgnat": bool(cgnat),
            "conclusiones": conclusiones}


def ip_publica() -> str:
    try:
        req = urllib.request.Request("https://api.ipify.org?format=json",
                                     headers={"User-Agent": "redportes"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())["ip"]
    except Exception:
        return ""


def describir_dns(servidores: list[str], puerta: str) -> list[dict]:
    res = []
    for ip in servidores:
        if ip in DNS_CONOCIDOS:
            quien = f"Público ({DNS_CONOCIDOS[ip]})"
        elif ip == puerta:
            quien = "El router"
        elif es_privada(ip):
            quien = "Servidor local"
        elif ip.startswith("127."):
            quien = "Resolución local del equipo"
        else:
            quien = "Probablemente del operador"
        res.append({"ip": ip, "quien": quien})
    return res


def revisar(puerta: str) -> dict:
    cmd = comando_traza()
    if cmd is None:
        res = analizar_saltos([], puerta)
        res["conclusiones"] = ["No se encontró traceroute/tracepath en este equipo; "
                               "instalalo para analizar la salida a Internet."]
    else:
        res = analizar_saltos(parsear_traza(ejecutar(cmd, timeout=60)), puerta)
    res["ip_publica"] = ip_publica()
    return res
