"""Escaneo de puertos TCP por conexión completa (no requiere permisos de administrador)."""

from __future__ import annotations

import http.client
import re
import socket
import ssl
import struct
from concurrent.futures import ThreadPoolExecutor

from redportes.modelo import Puerto

SERVICIOS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP", 111: "RPC",
    135: "MS-RPC", 139: "NetBIOS", 443: "HTTPS", 445: "SMB", 515: "LPD", 554: "RTSP",
    631: "IPP", 1433: "SQL Server", 1723: "PPTP", 2049: "NFS", 3306: "MySQL",
    3389: "Escritorio remoto (RDP)", 5000: "HTTP alt / UPnP", 5060: "SIP", 5432: "PostgreSQL",
    5900: "VNC", 6379: "Redis", 8000: "HTTP alt", 8006: "Proxmox", 8080: "HTTP alt",
    8081: "HTTP alt", 8291: "Winbox", 8443: "HTTPS alt", 8728: "API MikroTik",
    8729: "API-SSL MikroTik", 9100: "Impresión directa", 10050: "Agente Zabbix",
    27017: "MongoDB", 37777: "Dahua",
}

RAPIDO = [21, 22, 23, 53, 80, 135, 139, 443, 445, 554, 631, 3389, 5060, 5900,
          8000, 8080, 8291, 8443, 8728, 9100, 37777]
COMPLETO = sorted(SERVICIOS)

_HTTP = {80, 5000, 8000, 8006, 8080, 8081, 8443, 443}
_HTTPS = {443, 8443, 8006}
_BANNER = {21, 22, 23, 25}


def lista_de_puertos(spec: str) -> list[int]:
    """'rapido', 'completo', 'ninguno' o una lista tipo '22,80,8000-8010'."""
    spec = (spec or "rapido").strip().lower()
    if spec in ("rapido", "rápido", "comun", "común"):
        return list(RAPIDO)
    if spec == "completo":
        return list(COMPLETO)
    if spec in ("ninguno", "no", "0"):
        return []
    res: set[int] = set()
    for parte in spec.split(","):
        parte = parte.strip()
        if "-" in parte:
            a, b = parte.split("-", 1)
            res.update(range(int(a), int(b) + 1))
        elif parte:
            res.add(int(parte))
    if any(p < 1 or p > 65535 for p in res):
        raise ValueError("Los puertos van de 1 a 65535.")
    return sorted(res)


def puerto_abierto(ip: str, puerto: int, timeout: float = 0.8) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, puerto)) == 0
    except OSError:
        return False
    finally:
        s.close()


def leer_banner(ip: str, puerto: int, timeout: float = 2.5) -> str:
    try:
        with socket.create_connection((ip, puerto), timeout=timeout) as s:
            s.settimeout(timeout)
            datos = s.recv(256)
    except OSError:
        return ""
    # Telnet arranca con negociación IAC (0xFF ...): la descartamos.
    datos = re.sub(rb"\xff[\xfb-\xfe].", b"", datos)
    texto = datos.decode("utf-8", errors="replace")
    texto = "".join(c for c in texto if c.isprintable() or c == " ")
    return texto.strip()[:120]


def titulo_web(ip: str, puerto: int, https: bool, timeout: float = 3) -> tuple[str, bool]:
    """Devuelve (título, es_https). Prueba HTTPS si HTTP falla en puertos alternativos."""
    intentos = [https, not https] if puerto not in (80, 443) else [https]
    for usar_tls in intentos:
        try:
            if usar_tls:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                c = http.client.HTTPSConnection(ip, puerto, timeout=timeout, context=ctx)
            else:
                c = http.client.HTTPConnection(ip, puerto, timeout=timeout)
            c.request("GET", "/", headers={"User-Agent": "redportes", "Connection": "close"})
            r = c.getresponse()
            cuerpo = r.read(65536).decode("utf-8", errors="replace")
            servidor = r.getheader("Server", "") or ""
            c.close()
            m = re.search(r"<title[^>]*>(.*?)</title>", cuerpo, re.I | re.S)
            titulo = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
            return (titulo or servidor or f"HTTP {r.status}")[:100], usar_tls
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError):
            continue
    return "", https


# ---------------------------------------------------------------- SMBv1

def _paquete_smb1() -> bytes:
    dialecto = b"\x02NT LM 0.12\x00"
    cabecera = (
        b"\xffSMB" + b"\x72" + b"\x00" * 4 + b"\x18" + struct.pack("<H", 0xC853)
        + b"\x00" * 2 + b"\x00" * 8 + b"\x00" * 2      # pid alto, firma, reservado
        + b"\x00\x00" + struct.pack("<H", 0xFEFF)      # tid, pid
        + b"\x00\x00" + b"\x00\x00"                    # uid, mid
    )
    cuerpo = b"\x00" + struct.pack("<H", len(dialecto)) + dialecto
    smb = cabecera + cuerpo
    return b"\x00" + len(smb).to_bytes(3, "big") + smb


def acepta_smbv1(ip: str, timeout: float = 3) -> bool:
    """Ofrece solo el dialecto SMBv1 y mira si el equipo lo acepta. No autentica."""
    try:
        with socket.create_connection((ip, 445), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(_paquete_smb1())
            r = s.recv(1024)
    except OSError:
        return False
    return len(r) >= 13 and r[4:8] == b"\xffSMB" and r[9:13] == b"\x00\x00\x00\x00"


# ---------------------------------------------------------------- todo junto

def escanear(ips: list[str], puertos: list[int], progreso=lambda m: None) -> dict[str, list[Puerto]]:
    res: dict[str, list[Puerto]] = {ip: [] for ip in ips}
    if not puertos or not ips:
        return res
    pares = [(ip, p) for ip in ips for p in puertos]
    progreso(f"Revisando {len(puertos)} puertos en {len(ips)} equipos…")
    abiertos = []
    with ThreadPoolExecutor(max_workers=400) as ex:
        for n, (par, ok) in enumerate(zip(pares, ex.map(lambda x: puerto_abierto(*x), pares)), 1):
            if ok:
                abiertos.append(par)
            if len(pares) > 20000 and n % (len(pares) // 10) == 0:
                progreso(f"Puertos: {n}/{len(pares)} pruebas, {len(abiertos)} abiertos…")

    def detalle(par):
        ip, p = par
        pu = Puerto(numero=p, servicio=SERVICIOS.get(p, ""))
        if p in _HTTP:
            pu.titulo, pu.https = titulo_web(ip, p, p in _HTTPS)
        elif p in _BANNER:
            pu.banner = leer_banner(ip, p)
        return ip, pu

    if abiertos:
        progreso(f"Identificando {len(abiertos)} servicios abiertos…")
    with ThreadPoolExecutor(max_workers=32) as ex:
        for ip, pu in ex.map(detalle, abiertos):
            res[ip].append(pu)
    for lista in res.values():
        lista.sort(key=lambda p: p.numero)
    return res
