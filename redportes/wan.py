"""IP WAN del router, preguntándole al propio router (solo lectura, no sale a Internet).

Sirve para ver la IP "privada" que el operador le da al router cuando hay CGNAT
(100.64.0.0/10) o doble NAT (otra IP privada). Se prueba:
1. UPnP IGD: acción GetExternalIPAddress.
2. NAT-PMP (RFC 6886): pedido de dirección externa al puerto UDP 5351.
"""

from __future__ import annotations

import re
import socket
import struct
import urllib.request
from urllib.parse import urljoin
from redportes.sistema import abrir_url

_SERVICIOS = ("WANIPConnection", "WANPPPConnection")
_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def servicios_wan(descripcion: str, url_base: str) -> list[tuple[str, str]]:
    """(serviceType, URL de control) de los servicios WAN en la descripción XML del router."""
    base = re.search(r"<URLBase>\s*([^<]+?)\s*</URLBase>", descripcion, re.I)
    base = base.group(1) if base else url_base
    res = []
    for bloque in re.findall(r"<service>(.*?)</service>", descripcion, re.I | re.S):
        tipo = re.search(r"<serviceType>\s*([^<]+?)\s*</serviceType>", bloque, re.I)
        control = re.search(r"<controlURL>\s*([^<]+?)\s*</controlURL>", bloque, re.I)
        if tipo and control and any(s in tipo.group(1) for s in _SERVICIOS):
            res.append((tipo.group(1), urljoin(base, control.group(1))))
    return res


def _soap_ip_externa(tipo: str, control: str, timeout: float) -> str:
    cuerpo = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:GetExternalIPAddress xmlns:u="{tipo}"/></s:Body></s:Envelope>'
    ).encode()
    req = urllib.request.Request(control, data=cuerpo, method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{tipo}#GetExternalIPAddress"',
        "User-Agent": "redportes",
    })
    with abrir_url(req, timeout=timeout) as r:
        texto = r.read(65536).decode("utf-8", errors="replace")
    m = re.search(r"<NewExternalIPAddress>\s*([^<]*?)\s*</NewExternalIPAddress>", texto, re.I)
    ip = m.group(1) if m else ""
    return ip if _IPV4.match(ip) and ip != "0.0.0.0" else ""


def por_upnp(ubicaciones: list[str], timeout: float = 4) -> str:
    for url in ubicaciones:
        try:
            with abrir_url(urllib.request.Request(url, headers={"User-Agent": "redportes"}),
                                        timeout=timeout) as r:
                desc = r.read(262144).decode("utf-8", errors="replace")
        except Exception:
            continue
        for tipo, control in servicios_wan(desc, url):
            try:
                ip = _soap_ip_externa(tipo, control, timeout)
            except Exception:
                continue
            if ip:
                return ip
    return ""


def parsear_natpmp(datos: bytes) -> str:
    if len(datos) < 12:
        return ""
    version, op, resultado = struct.unpack("!BBH", datos[:4])
    if version != 0 or op != 128 or resultado != 0:
        return ""
    ip = socket.inet_ntoa(datos[8:12])
    return "" if ip == "0.0.0.0" else ip


def por_natpmp(puerta: str, timeout: float = 1.5) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        for _ in range(2):
            s.sendto(b"\x00\x00", (puerta, 5351))
            try:
                datos, (origen, _) = s.recvfrom(64)
            except socket.timeout:
                continue
            if origen == puerta:
                return parsear_natpmp(datos)
    except OSError:
        pass
    finally:
        s.close()
    return ""


def describir(ip: str, metodo: str) -> dict:
    from redportes.internet import tipo_ip

    if not ip:
        return {"ip": "", "metodo": "", "tipo": "", "texto":
                "El router no informa su IP WAN (no tiene UPnP ni NAT-PMP activos, o no los soporta)."}
    tipo = tipo_ip(ip)
    textos = {
        "cgnat": f"El router recibe del operador la IP {ip}, del rango CGNAT (100.64.0.0/10): "
                 "comparte la IP pública con otros clientes y no se pueden abrir puertos desde afuera.",
        "privada": f"El router recibe una IP privada ({ip}): delante hay otro router o el módem del "
                   "operador haciendo NAT (doble NAT).",
        "publica": f"El router tiene IP pública ({ip}): se pueden publicar servicios con port forward.",
    }
    return {"ip": ip, "metodo": metodo, "tipo": tipo,
            "texto": textos.get(tipo, f"El router informa la IP WAN {ip}.")}


def origen(w: dict) -> str:
    """De dónde salió la IP WAN, en castellano."""
    m = w.get("metodo", "")
    if m.startswith("speedtest"):
        return f"según el {m}"
    return f"informada por el router vía {m}" if m else ""


def ip_wan(puerta: str, ubicaciones_igd: list[str]) -> dict:
    """{'ip', 'metodo' (UPnP | NAT-PMP), 'tipo' (cgnat | privada | publica), 'texto'}."""
    ip = por_upnp(ubicaciones_igd) if ubicaciones_igd else ""
    if ip:
        return describir(ip, "UPnP")
    ip = por_natpmp(puerta) if puerta else ""
    return describir(ip, "NAT-PMP" if ip else "")
