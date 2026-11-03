"""Barrido de ping rápido, sin lanzar un proceso por dirección.

- Linux/macOS: socket ICMP "datagram" (no requiere root si el sistema lo permite,
  como en Ubuntu, Debian y Fedora). Si no, socket raw (requiere root).
- Windows: IcmpSendEcho de iphlpapi.dll (no requiere administrador).
Si nada de eso está disponible, devuelve None y se usa el comando `ping`.
"""

from __future__ import annotations

import os
import select
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor

from redportes.sistema import ES_MAC, ES_WINDOWS


def _checksum(datos: bytes) -> int:
    if len(datos) % 2:
        datos += b"\x00"
    s = sum(struct.unpack(f"!{len(datos) // 2}H", datos))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


def _paquete(ident: int, seq: int) -> bytes:
    carga = b"redportes"
    cab = struct.pack("!BBHHH", 8, 0, 0, ident, seq)
    return struct.pack("!BBHHH", 8, 0, _checksum(cab + carga), ident, seq) + carga


# ---------------------------------------------------------------- Linux / macOS

def _abrir_socket():
    try:
        return socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP), "dgram"
    except OSError:
        pass
    try:
        return socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP), "raw"
    except OSError:
        return None, ""


def _barrido_socket(ips, timeout, tasa, progreso):
    s, modo = _abrir_socket()
    if s is None:
        return None
    ident = os.getpid() & 0xFFFF
    ip_recvttl = getattr(socket, "IP_RECVTTL", 24 if ES_MAC else 12)
    try:
        s.setsockopt(socket.IPPROTO_IP, ip_recvttl, 1)
    except OSError:
        pass
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass
    s.setblocking(False)

    enviado: dict[str, float] = {}
    res: dict[str, tuple[int | None, float]] = {}
    pendientes = set(ips)

    def recibir():
        while True:
            try:
                datos, anc, _flags, (origen, _) = s.recvmsg(512, socket.CMSG_SPACE(4))
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            ttl = None
            if datos and datos[0] >> 4 == 4:  # viene con cabecera IP (raw, o dgram en macOS)
                ihl = (datos[0] & 0x0F) * 4
                ttl = datos[8]
                datos = datos[ihl:]
            if len(datos) < 8 or datos[0] != 0:  # 0 = echo reply
                continue
            if modo == "raw" and struct.unpack("!H", datos[4:6])[0] != ident:
                continue
            for nivel, tipo, valor in anc:
                if nivel == socket.IPPROTO_IP and tipo in (2, ip_recvttl) and valor:
                    ttl = valor[0] if len(valor) == 1 else struct.unpack("i", valor[:4])[0]
            if origen in pendientes and origen not in res:
                res[origen] = (ttl, (time.monotonic() - enviado.get(origen, time.monotonic())) * 1000)

    try:
        intervalo = 1.0 / tasa
        siguiente_aviso = 0.1
        t_prox = time.monotonic()
        for n, ip in enumerate(ips):
            try:
                enviado[ip] = time.monotonic()
                s.sendto(_paquete(ident, n & 0xFFFF), (ip, 0))
            except (BlockingIOError, InterruptedError):
                select.select([], [s], [], 0.05)
            except OSError:
                pass  # p. ej. broadcast o red inalcanzable
            if n % 64 == 0:
                recibir()
            t_prox += intervalo
            espera = t_prox - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            if progreso and len(ips) > 2048 and (n + 1) / len(ips) >= siguiente_aviso:
                progreso(f"Ping: {n + 1}/{len(ips)} direcciones, {len(res)} responden…")
                siguiente_aviso += 0.1
        fin = time.monotonic() + timeout
        while time.monotonic() < fin:
            r, _, _ = select.select([s], [], [], max(0.0, fin - time.monotonic()))
            if r:
                recibir()
    finally:
        s.close()
    return res


# ---------------------------------------------------------------- Windows

def _barrido_windows(ips, timeout, progreso):
    import ctypes
    import threading

    try:
        iphlp = ctypes.windll.iphlpapi
    except (AttributeError, OSError):
        return None
    iphlp.IcmpCreateFile.restype = ctypes.c_void_p
    iphlp.IcmpSendEcho.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint16,
                                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
    iphlp.IcmpSendEcho.restype = ctypes.c_uint32
    iphlp.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
    # Offset del TTL dentro de ICMP_ECHO_REPLY: después de Address, Status, RTT,
    # DataSize, Reserved y el puntero Data.
    off_ttl = 16 + ctypes.sizeof(ctypes.c_void_p)
    local = threading.local()
    manijas = []
    carga = ctypes.create_string_buffer(b"redportes", 9)
    ms = int(timeout * 1000)

    def uno(ip):
        if not hasattr(local, "h"):
            local.h = iphlp.IcmpCreateFile()
            manijas.append(local.h)
        buf = ctypes.create_string_buffer(256)
        dest = int.from_bytes(socket.inet_aton(ip), "little")
        n = iphlp.IcmpSendEcho(local.h, dest, carga, 9, None, buf, 256, ms)
        if n == 0:
            return ip, None
        addr, estado, rtt = struct.unpack_from("<III", buf.raw, 0)
        if estado != 0 or addr != dest:
            return ip, None
        return ip, (buf.raw[off_ttl], float(rtt))

    res = {}
    try:
        with ThreadPoolExecutor(max_workers=512) as ex:
            for n, (ip, r) in enumerate(ex.map(uno, ips)):
                if r:
                    res[ip] = r
                if progreso and len(ips) > 2048 and n and n % (len(ips) // 10) == 0:
                    progreso(f"Ping: {n}/{len(ips)} direcciones, {len(res)} responden…")
    finally:
        for h in manijas:
            iphlp.IcmpCloseHandle(h)
    return res


# ---------------------------------------------------------------- API

def barrido(ips: list[str], timeout: float = 1.0, tasa: int = 2000,
            progreso=None) -> dict[str, tuple[int | None, float]] | None:
    """Devuelve {ip: (ttl, latencia_ms)} de las que respondieron, o None si no hay método."""
    if not ips:
        return {}
    if ES_WINDOWS:
        return _barrido_windows(ips, timeout, progreso)
    return _barrido_socket(ips, timeout, tasa, progreso)


def tiempo_estimado(cantidad: int, tasa: int = 2000) -> float:
    """Segundos aproximados del barrido de ping."""
    if ES_WINDOWS:
        return cantidad / 512 * 1.0
    return cantidad / tasa + 1.0
