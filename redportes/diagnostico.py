"""Diagnóstico rápido de conexión: gateway, Internet, DNS y navegación.

Responde a la pregunta de todos los días: «¿anda mal la red, el proveedor o el DNS?».
"""

from __future__ import annotations

import http.client
import random
import socket
import ssl
import statistics
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime

from redportes import icmp
from redportes.descubrimiento import hacer_ping
from redportes.red import puerta_de_enlace, servidores_dns
from redportes.sistema import tiene

DESTINOS_INTERNET = {"8.8.8.8": "Google", "1.1.1.1": "Cloudflare"}
DNS_REFERENCIA = "1.1.1.1"
NOMBRE_PRUEBA = "www.google.com"
URL_HTTPS = ("www.google.com", "/generate_204")


@dataclass
class Prueba:
    nombre: str
    estado: str      # ok | aviso | falla | info
    resultado: str
    detalle: str = ""


# ---------------------------------------------------------------- mediciones

def ping_serie(ip: str, n: int = 10, intervalo: float = 0.2, timeout: float = 1.0) -> dict:
    """n pings a una IP: pérdida, mínimo, promedio, máximo y jitter (variación entre pings)."""
    tiempos: list[float] = []
    for i in range(n):
        r = icmp.barrido([ip], timeout=timeout)
        if r is None:  # sin socket ICMP: comando ping
            ttl, lat = hacer_ping(ip) if tiene("ping") else (None, None)
            if ttl is not None:
                tiempos.append(lat if lat is not None else 0.0)
        elif ip in r:
            tiempos.append(r[ip][1])
        if i < n - 1:
            time.sleep(intervalo)
    res = {"ip": ip, "enviados": n, "recibidos": len(tiempos),
           "perdida": round(100 * (n - len(tiempos)) / n)}
    if tiempos:
        difs = [abs(a - b) for a, b in zip(tiempos, tiempos[1:])]
        res.update(min=round(min(tiempos), 1), prom=round(statistics.mean(tiempos), 1),
                   max=round(max(tiempos), 1), jitter=round(statistics.mean(difs), 1) if difs else 0.0)
    return res


def _consulta_dns(nombre: str) -> tuple[int, bytes]:
    ident = random.randint(0, 0xFFFF)
    cab = struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in nombre.split(".")) + b"\x00"
    return ident, cab + qname + struct.pack("!HH", 1, 1)


def dns_directo(servidor: str, nombre: str = NOMBRE_PRUEBA, timeout: float = 2.0, puerto: int = 53) -> dict:
    """Pregunta un registro A directamente a un servidor DNS (UDP 53)."""
    ident, paquete = _consulta_dns(nombre)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    inicio = time.monotonic()
    try:
        s.sendto(paquete, (servidor, puerto))
        while True:
            datos, (origen, _) = s.recvfrom(2048)
            if len(datos) >= 12 and struct.unpack("!H", datos[:2])[0] == ident:
                break
    except socket.timeout:
        return {"servidor": servidor, "ok": False, "error": "no responde"}
    except OSError as e:
        return {"servidor": servidor, "ok": False, "error": _error_amigable(e)}
    finally:
        s.close()
    ms = round((time.monotonic() - inicio) * 1000, 1)
    flags, _qd, respuestas = struct.unpack("!HHH", datos[2:8])
    rcode = flags & 0x0F
    if rcode != 0 or respuestas == 0:
        error = {2: "falla del servidor (SERVFAIL)", 3: "dice que el nombre no existe",
                 5: "rechaza la consulta"}.get(rcode, f"respuesta vacía (código {rcode})")
        return {"servidor": servidor, "ok": False, "ms": ms, "error": error}
    return {"servidor": servidor, "ok": True, "ms": ms}


def _error_amigable(e: OSError) -> str:
    if isinstance(e, socket.gaierror):
        return "no se pudo resolver el nombre (DNS)"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "no respondió a tiempo"
    if isinstance(e, ConnectionRefusedError):
        return "conexión rechazada"
    return str(e)


def resolver_sistema(nombre: str = NOMBRE_PRUEBA) -> dict:
    inicio = time.monotonic()
    try:
        socket.getaddrinfo(nombre, 443, socket.AF_INET)
    except OSError as e:
        return {"ok": False, "error": _error_amigable(e)}
    return {"ok": True, "ms": round((time.monotonic() - inicio) * 1000, 1)}


def https(host: str = URL_HTTPS[0], ruta: str = URL_HTTPS[1], timeout: float = 6) -> dict:
    inicio = time.monotonic()
    try:
        c = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ssl.create_default_context())
        c.request("GET", ruta, headers={"User-Agent": "redportes"})
        estado = c.getresponse().status
        c.close()
    except ssl.SSLError as e:
        return {"ok": False, "error": f"certificado o TLS interceptado ({e.reason})"}
    except OSError as e:
        return {"ok": False, "error": _error_amigable(e)}
    ms = round((time.monotonic() - inicio) * 1000)
    if estado != 204:
        return {"ok": False, "ms": ms, "error": f"respondió {estado} en vez de 204 (¿portal cautivo o proxy?)"}
    return {"ok": True, "ms": ms}


# ---------------------------------------------------------------- evaluación

def _texto_ping(p: dict) -> str:
    if not p.get("recibidos"):
        return f"sin respuesta ({p['enviados']} enviados)"
    return (f"pérdida {p['perdida']}% · promedio {p['prom']} ms (mín {p['min']} / máx {p['max']}) "
            f"· jitter {p['jitter']} ms")


def evaluar(gw: str, p_gw: dict | None, p_inet: dict[str, dict], dns_cfg: list[dict],
            dns_ref: dict, sistema: dict, web: dict) -> tuple[list[Prueba], list[str]]:
    pruebas: list[Prueba] = []
    concl: list[str] = []

    # Gateway
    if not gw:
        pruebas.append(Prueba("Puerta de enlace", "falla", "no hay puerta de enlace configurada"))
        concl.append("El equipo no tiene puerta de enlace: revisar el cable/Wi-Fi o el DHCP del router.")
    else:
        if not p_gw["recibidos"]:
            est = "falla"
        elif p_gw["perdida"] >= 5 or p_gw["prom"] > 30:
            est = "aviso"
        else:
            est = "ok"
        pruebas.append(Prueba(f"Ping al router ({gw})", est, _texto_ping(p_gw)))
        if est == "falla":
            concl.append(f"El router ({gw}) no responde al ping. Puede tener el ping bloqueado; si además "
                         "no hay Internet, el problema está en la conexión local (cable, Wi-Fi o el router).")
        elif est == "aviso":
            concl.append("Hay pérdida o demora hasta el propio router: el problema está en la red local "
                         "(señal Wi-Fi débil, interferencia, cable o switch con fallas, o red saturada).")

    # Internet
    gw_ok = bool(p_gw and p_gw["recibidos"] and p_gw["perdida"] < 5)
    sin_respuesta = 0
    for ip, p in p_inet.items():
        nombre = DESTINOS_INTERNET.get(ip, ip)
        if not p["recibidos"]:
            est = "falla"
            sin_respuesta += 1
        elif p["perdida"] >= 5 or p["prom"] > 150 or p["jitter"] > 30:
            est = "aviso"
        else:
            est = "ok"
        pruebas.append(Prueba(f"Ping a Internet ({ip}, {nombre})", est, _texto_ping(p)))
    peor = max(p_inet.values(), key=lambda x: (x["perdida"], x.get("prom", 0)))
    if sin_respuesta == len(p_inet):
        if web.get("ok"):
            concl.append("El ping hacia Internet está bloqueado, pero la navegación funciona: no es una "
                         "falla, es un firewall que filtra ICMP.")
        else:
            concl.append("No hay salida a Internet. Si el router responde bien, el problema está en el "
                         "router o en el proveedor: revisar el módem/ONT y llamar al proveedor.")
    elif peor["perdida"] >= 5 and gw_ok:
        concl.append(f"Hay {peor['perdida']}% de pérdida hacia Internet pero no dentro de la red: el problema "
                     "está del router hacia afuera (proveedor o enlace).")
    elif peor.get("prom", 0) > 150:
        concl.append(f"La latencia a Internet es alta ({peor['prom']} ms): normal en enlaces satelitales "
                     "o radioenlaces largos, si no, consultar al proveedor.")
    if peor.get("jitter", 0) > 30:
        concl.append(f"El jitter es alto ({peor['jitter']} ms): puede cortar llamadas de VoIP y "
                     "videollamadas.")

    # DNS
    for d in dns_cfg:
        if d["ok"]:
            est = "aviso" if d["ms"] > 300 else "ok"
            pruebas.append(Prueba(f"DNS configurado {d['servidor']}", est, f"responde en {d['ms']} ms"))
        else:
            pruebas.append(Prueba(f"DNS configurado {d['servidor']}", "falla", d["error"]))
    pruebas.append(Prueba(f"DNS de referencia {DNS_REFERENCIA}", "ok" if dns_ref["ok"] else "falla",
                          f"responde en {dns_ref['ms']} ms" if dns_ref["ok"] else dns_ref["error"]))
    malos = [d["servidor"] for d in dns_cfg if not d["ok"]]
    if malos and dns_ref["ok"]:
        concl.append(f"El DNS configurado {', '.join(malos)} no funciona, pero un DNS público sí: por eso "
                     "«hay Internet pero no abren las páginas». Corregir el DNS en el router/DHCP o "
                     "usar 1.1.1.1 / 8.8.8.8.")
    lentos = [d for d in dns_cfg if d["ok"] and d["ms"] > 300]
    if lentos:
        concl.append(f"El DNS {lentos[0]['servidor']} tarda {lentos[0]['ms']} ms: las páginas van a "
                     "demorar en empezar a cargar.")

    pruebas.append(Prueba(f"Resolver {NOMBRE_PRUEBA} (sistema)", "ok" if sistema["ok"] else "falla",
                          f"{sistema['ms']} ms" if sistema["ok"] else sistema["error"]))

    # Navegación
    pruebas.append(Prueba("Navegación HTTPS (google.com)", "ok" if web["ok"] else "falla",
                          f"{web['ms']} ms" if web["ok"] else web["error"]))
    if not web["ok"] and dns_ref["ok"] and any(p["recibidos"] for p in p_inet.values()):
        concl.append("Hay conexión, pero no se puede navegar por HTTPS: puede haber un proxy, un portal "
                     "cautivo (Wi-Fi de hotel/bar) o un firewall que intercepta.")

    if not concl:
        concl.append("Todo bien: la red local, la salida a Internet, el DNS y la navegación responden "
                     "normalmente.")
    return pruebas, concl


def ejecutar(progreso=lambda m: None) -> dict:
    gw = puerta_de_enlace()
    dns = [d for d in servidores_dns() if not d.startswith("127.")]
    progreso("Probando router, Internet y DNS…")
    with ThreadPoolExecutor(max_workers=8) as ex:
        f_gw = ex.submit(ping_serie, gw) if gw else None
        f_inet = {ip: ex.submit(ping_serie, ip) for ip in DESTINOS_INTERNET}
        f_dns = [ex.submit(dns_directo, d) for d in dns]
        f_ref = ex.submit(dns_directo, DNS_REFERENCIA)
        f_sis = ex.submit(resolver_sistema)
        f_web = ex.submit(https)
        pruebas, concl = evaluar(gw, f_gw.result() if f_gw else None,
                                 {ip: f.result() for ip, f in f_inet.items()},
                                 [f.result() for f in f_dns], f_ref.result(), f_sis.result(), f_web.result())
    return {"fecha": datetime.now().isoformat(timespec="seconds"), "puerta": gw,
            "pruebas": [asdict(p) for p in pruebas], "conclusiones": concl}


ICONO = {"ok": "✅", "aviso": "⚠️", "falla": "❌", "info": "ℹ️"}


def como_texto(d: dict) -> str:
    """Resumen para copiar y pegar en un chat o ticket."""
    fecha = datetime.fromisoformat(d["fecha"]).strftime("%d/%m/%Y %H:%M")
    lineas = [f"Diagnóstico de conexión — {fecha}"]
    lineas += [f"{ICONO[p['estado']]} {p['nombre']}: {p['resultado']}" for p in d["pruebas"]]
    lineas += ["", "Conclusión:"] + [f"• {c}" for c in d["conclusiones"]]
    return "\n".join(lineas)
