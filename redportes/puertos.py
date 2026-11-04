"""Escaneo de puertos TCP por conexión completa (no requiere permisos de administrador)."""

from __future__ import annotations

import errno
import http.client
import re
import socket
import ssl
import struct
from urllib.parse import urljoin, urlsplit
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


def estado_puerto(ip: str, puerto: int, timeout: float = 0.8) -> str:
    """'abierto', 'cerrado' (el equipo contesta que no) o 'filtrado' (no contesta: firewall)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        r = s.connect_ex((ip, puerto))
    except OSError:
        return "filtrado"
    finally:
        s.close()
    if r == 0:
        return "abierto"
    if r in (errno.ECONNREFUSED, 10061):
        return "cerrado"
    return "filtrado"


def puerto_abierto(ip: str, puerto: int, timeout: float = 0.8) -> bool:
    return estado_puerto(ip, puerto, timeout) == "abierto"


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


def _pedir(ip: str, puerto: int, tls: bool, ruta: str, timeout: float):
    if tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        c = http.client.HTTPSConnection(ip, puerto, timeout=timeout, context=ctx)
    else:
        c = http.client.HTTPConnection(ip, puerto, timeout=timeout)
    try:
        c.request("GET", ruta or "/", headers={"User-Agent": "redportes", "Connection": "close",
                                                "Host": ip if puerto in (80, 443) else f"{ip}:{puerto}"})
        r = c.getresponse()
        cuerpo = r.read(65536).decode("utf-8", errors="replace")
        return r.status, r.getheader("Location", "") or "", r.getheader("Server", "") or "", cuerpo
    finally:
        c.close()


_META_REFRESH = re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*content=["']?\s*\d+\s*;\s*url=([^"'>]+)""", re.I)


def titulo_web(ip: str, puerto: int, https: bool, timeout: float = 3) -> tuple[str, bool, bool]:
    """Devuelve (título, es_https, redirige_a_https).

    Sigue hasta 4 redirecciones (HTTP o <meta refresh>) dentro del mismo equipo, para
    mostrar el título real del panel en vez de «302» o «Redirecting…».
    """
    intentos = [https, not https] if puerto not in (80, 443) else [https]
    for tls_inicial in intentos:
        tls, p, ruta = tls_inicial, puerto, "/"
        a_https = False
        try:
            for _ in range(5):
                estado, destino, servidor, cuerpo = _pedir(ip, p, tls, ruta, timeout)
                if not destino and estado == 200:
                    m = _META_REFRESH.search(cuerpo)
                    destino = m.group(1).strip() if m else ""
                if not destino:
                    break
                actual = f"{'https' if tls else 'http'}://{ip}:{p}{ruta}"
                u = urlsplit(urljoin(actual, destino))
                if u.hostname and u.hostname != ip:
                    return (f"→ {u.scheme}://{u.hostname}{u.path}")[:100], tls_inicial, u.scheme == "https"
                tls = u.scheme == "https"
                p = u.port or (443 if tls else 80)
                ruta = u.path + (f"?{u.query}" if u.query else "") or "/"
                if tls and not tls_inicial:
                    a_https = True
            m = re.search(r"<title[^>]*>(.*?)</title>", cuerpo, re.I | re.S)
            titulo = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
            return (titulo or servidor or f"HTTP {estado}")[:100], tls_inicial, a_https
        except (OSError, http.client.HTTPException, ssl.SSLError, ValueError):
            continue
    return "", https, False


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

def escanear(ips: list[str], puertos: list[int], progreso=lambda m: None, parar=lambda: False,
             avisar=lambda texto, recomendacion="": None, limite_detalle: float = 45) -> dict[str, list[Puerto]]:
    from concurrent.futures import FIRST_COMPLETED, wait as esperar

    res: dict[str, list[Puerto]] = {ip: [] for ip in ips}
    if not puertos or not ips:
        return res
    pares = [(ip, p) for ip in ips for p in puertos]
    progreso(f"Revisando {len(puertos)} puertos en {len(ips)} equipos…")
    abiertos = []
    filtrados: dict[str, int] = {}
    ex = ThreadPoolExecutor(max_workers=400)
    futuros = {ex.submit(estado_puerto, ip, p): (ip, p) for ip, p in pares}
    pendientes = set(futuros)
    hechos_total = 0
    try:
        while pendientes:
            hechos, pendientes = esperar(pendientes, timeout=0.3, return_when=FIRST_COMPLETED)
            for f in hechos:
                ip, p = futuros[f]
                estado = f.result()
                if estado == "abierto":
                    abiertos.append((ip, p))
                elif estado == "filtrado":
                    filtrados[ip] = filtrados.get(ip, 0) + 1
            hechos_total += len(hechos)
            if len(pares) > 20000 and hechos and hechos_total % max(1, len(pares) // 10) < len(hechos):
                progreso(f"Puertos: {hechos_total}/{len(pares)} pruebas, {len(abiertos)} abiertos…")
            if parar():
                avisar(f"La revisión de puertos se cortó antes de terminar ({hechos_total} de {len(pares)} pruebas).",
                       "Los resultados de puertos pueden estar incompletos. Para un equipo puntual, escaneá "
                       "solo su IP (campo Red) o puertos específicos.")
                break
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    # Equipos que no contestan en la mayoría de los puertos: tienen firewall y hacen esperar cada prueba.
    con_firewall = [ip for ip, n in filtrados.items() if len(puertos) >= 5 and n >= 0.6 * len(puertos)]
    if con_firewall and len(con_firewall) <= 20:
        avisar(f"{len(con_firewall)} equipo(s) no contestan en la mayoría de los puertos (firewall): "
               + ", ".join(con_firewall[:8]) + ("…" if len(con_firewall) > 8 else "") + ".",
               "Puede haber servicios que no se vieron. Si tenés que revisar alguno, escaneá esa IP con "
               "los puertos que te interesan (por ejemplo 22,80,443,3389).")

    def detalle(par):
        ip, p = par
        pu = Puerto(numero=p, servicio=SERVICIOS.get(p, ""))
        if p in _HTTP:
            pu.titulo, pu.https, pu.a_https = titulo_web(ip, p, p in _HTTPS)
        elif p in _BANNER:
            pu.banner = leer_banner(ip, p)
        return ip, pu

    if abiertos and not parar():
        progreso(f"Identificando {len(abiertos)} servicios abiertos…")
        ex = ThreadPoolExecutor(max_workers=32)
        futuros = {ex.submit(detalle, par): par for par in abiertos}
        pendientes = set(futuros)
        import time

        fin = time.monotonic() + limite_detalle
        try:
            while pendientes and time.monotonic() < fin and not parar():
                hechos, pendientes = esperar(pendientes, timeout=0.3, return_when=FIRST_COMPLETED)
                for f in hechos:
                    try:
                        ip, pu = f.result()
                        res[ip].append(pu)
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        # Lo que no llegó a identificarse queda igual como puerto abierto, sin título.
        for f in pendientes:
            ip, p = futuros[f]
            res[ip].append(Puerto(numero=p, servicio=SERVICIOS.get(p, "")))
        if pendientes:
            avisar(f"{len(pendientes)} servicio(s) tardaron demasiado en responder y no se identificaron.",
                   "Suelen ser paneles web lentos o equipos saturados. Abrilos a mano para ver qué son.")
    elif abiertos:
        for ip, p in abiertos:
            res[ip].append(Puerto(numero=p, servicio=SERVICIOS.get(p, "")))
    for lista in res.values():
        lista.sort(key=lambda p: p.numero)
    return res
