"""Consultar un dominio en varios DNS a la vez y comparar las respuestas.

Responde: «¿por qué a mí no me abre y a otros sí?». Detecta caché vieja
(un DNS dice que no existe y los demás sí lo resuelven), bloqueos (0.0.0.0) y
respuestas distintas entre servidores.
"""

from __future__ import annotations

import random
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor

from redportes.red import es_privada, servidores_dns

PUBLICOS = {"1.1.1.1": "Cloudflare", "8.8.8.8": "Google", "9.9.9.9": "Quad9", "208.67.222.222": "OpenDNS"}


def armar_consulta(nombre: str, tipo: int = 1) -> tuple[int, bytes]:
    ident = random.randint(0, 0xFFFF)
    cab = struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode("idna") for p in nombre.strip(".").split(".")) + b"\x00"
    return ident, cab + qname + struct.pack("!HH", tipo, 1)


def _leer_nombre(datos: bytes, pos: int) -> tuple[str, int]:
    """Lee un nombre DNS (con compresión). Devuelve (nombre, posición siguiente)."""
    partes, saltos, fin = [], 0, None
    while True:
        largo = datos[pos]
        if largo & 0xC0 == 0xC0:  # puntero
            if fin is None:
                fin = pos + 2
            pos = ((largo & 0x3F) << 8) | datos[pos + 1]
            saltos += 1
            if saltos > 20:
                raise ValueError("nombre DNS inválido")
            continue
        if largo == 0:
            pos += 1
            break
        partes.append(datos[pos + 1:pos + 1 + largo].decode("ascii", "replace"))
        pos += 1 + largo
    return ".".join(partes), (fin if fin is not None else pos)


def parsear_respuesta(datos: bytes) -> dict:
    """{'rcode', 'ips', 'cname', 'ttl', 'ttl_negativo'} de una respuesta DNS."""
    _id, flags, qd, an, ns, _ar = struct.unpack("!HHHHHH", datos[:12])
    pos = 12
    for _ in range(qd):
        _, pos = _leer_nombre(datos, pos)
        pos += 4
    res = {"rcode": flags & 0x0F, "ips": [], "cname": "", "ttl": None, "ttl_negativo": None}
    for i in range(an + ns):
        _, pos = _leer_nombre(datos, pos)
        tipo, _clase, ttl, largo = struct.unpack("!HHIH", datos[pos:pos + 10])
        pos += 10
        rdata_pos = pos
        pos += largo
        if i < an:
            if tipo == 1 and largo == 4:
                res["ips"].append(socket.inet_ntoa(datos[rdata_pos:rdata_pos + 4]))
                res["ttl"] = ttl if res["ttl"] is None else min(res["ttl"], ttl)
            elif tipo == 5 and not res["cname"]:
                res["cname"], _ = _leer_nombre(datos, rdata_pos)
        elif tipo == 6:  # SOA en autoridad: cuánto se guarda una respuesta negativa
            p = rdata_pos
            _, p = _leer_nombre(datos, p)
            _, p = _leer_nombre(datos, p)
            minimo = struct.unpack("!I", datos[p + 16:p + 20])[0]
            res["ttl_negativo"] = min(ttl, minimo)
    return res


def consultar(servidor: str, nombre: str, timeout: float = 2.5, puerto: int = 53) -> dict:
    ident, paquete = armar_consulta(nombre)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    inicio = time.monotonic()
    try:
        s.sendto(paquete, (servidor, puerto))
        while True:
            datos, _ = s.recvfrom(4096)
            if len(datos) >= 12 and struct.unpack("!H", datos[:2])[0] == ident:
                break
    except socket.timeout:
        return {"servidor": servidor, "estado": "sin respuesta"}
    except OSError as e:
        return {"servidor": servidor, "estado": "error", "detalle": str(e)}
    finally:
        s.close()
    ms = round((time.monotonic() - inicio) * 1000, 1)
    try:
        r = parsear_respuesta(datos)
    except (ValueError, IndexError, struct.error):
        return {"servidor": servidor, "estado": "respuesta inválida", "ms": ms}
    estado = {0: "ok", 2: "falla del servidor", 3: "no existe", 5: "rechazada"}.get(r["rcode"], f"código {r['rcode']}")
    if estado == "ok" and not r["ips"]:
        estado = "sin direcciones"
    if estado == "ok" and all(ip in ("0.0.0.0", "127.0.0.1") for ip in r["ips"]):
        estado = "bloqueado"
    return {"servidor": servidor, "estado": estado, "ms": ms, **r}


def limpiar(texto: str) -> str:
    """De lo que pegue el usuario (URL completa, con puerto, con espacios) saca solo el dominio."""
    t = texto.strip().lower()
    if "://" in t:
        t = t.split("://", 1)[1]
    t = t.split("/")[0].split("?")[0].split("#")[0]
    t = t.split("@")[-1]          # usuario:clave@dominio
    t = t.split(":")[0]           # puerto
    return t.strip(". ")


def comparar(nombre: str, extra: list[str] | None = None) -> dict:
    """Consulta el dominio en los DNS de la PC y en los públicos, y saca conclusiones."""
    nombre = limpiar(nombre)
    if not nombre or "." not in nombre:
        raise ValueError("Escribí un dominio, por ejemplo: www.google.com")
    locales = [d for d in servidores_dns() if not d.startswith("127.")]
    servidores = list(dict.fromkeys(locales + list(PUBLICOS) + (extra or [])))
    with ThreadPoolExecutor(max_workers=len(servidores)) as ex:
        resultados = list(ex.map(lambda s: consultar(s, nombre), servidores))
    for r in resultados:
        s = r["servidor"]
        r["quien"] = (PUBLICOS[s] + " (público)" if s in PUBLICOS else
                      "DNS de la PC (red local)" if es_privada(s) else "DNS de la PC")
        r["de_la_pc"] = s in locales
    return {"dominio": nombre, "resultados": resultados, "conclusiones": conclusiones(nombre, resultados)}


def _minutos(seg: int | None) -> str:
    if seg is None:
        return ""
    if seg < 90:
        return f"{seg} segundos"
    if seg < 5400:
        return f"{round(seg / 60)} minutos"
    return f"{round(seg / 3600, 1)} horas".replace(".0 ", " ")


def conclusiones(nombre: str, res: list[dict]) -> list[str]:
    pc = [r for r in res if r["de_la_pc"]]
    pub = [r for r in res if not r["de_la_pc"]]
    pub_ok = [r for r in pub if r["estado"] == "ok"]
    c = []
    if not pub_ok and all(r["estado"] == "no existe" for r in pub):
        return [f"«{nombre}» no existe para ningún DNS público: revisá que esté bien escrito o que el "
                "dominio tenga el registro cargado."]
    if not any(r["estado"] in ("ok", "no existe", "bloqueado") for r in res):
        return ["Ningún DNS respondió: no hay salida a Internet o algo bloquea el puerto 53."]
    for r in pc:
        if r["estado"] == "no existe" and pub_ok:
            espera = _minutos(r.get("ttl_negativo"))
            c.append(f"El DNS de la PC {r['servidor']} dice que «{nombre}» no existe, pero los públicos sí lo "
                     "encuentran: tiene guardada una respuesta vieja"
                     + (f" y la va a seguir dando hasta {espera} más" if espera else "")
                     + ". Para entrar ya: cambiar el DNS (por ejemplo a 1.1.1.1), usar datos móviles o reiniciar el router.")
        elif r["estado"] == "bloqueado":
            c.append(f"El DNS de la PC {r['servidor']} bloquea «{nombre}» (responde 0.0.0.0): suele ser un "
                     "filtro como AdGuard, Pi-hole o el firewall de la red.")
        elif r["estado"] in ("sin respuesta", "error", "falla del servidor", "rechazada"):
            c.append(f"El DNS de la PC {r['servidor']} no responde bien ({r['estado']}): las páginas van a "
                     "fallar o tardar. Revisar ese servidor o usar otro.")
        elif r["estado"] == "ok" and pub_ok:
            publicas = set().union(*(set(p["ips"]) for p in pub_ok))
            if r["ips"] and not set(r["ips"]) & publicas and not (r.get("cname") and any(p.get("cname") == r["cname"] for p in pub_ok)):
                c.append(f"El DNS de la PC {r['servidor']} devuelve otras direcciones ({', '.join(r['ips'][:3])}) "
                         "que los públicos. Puede ser normal en sitios grandes con varios servidores, o un DNS "
                         "interno con otra versión del sitio; si el sitio no abre, puede estar redirigido.")
    lentos = [r for r in pc if r["estado"] == "ok" and r.get("ms", 0) > 300]
    for r in lentos:
        c.append(f"El DNS de la PC {r['servidor']} tarda {r['ms']} ms en responder: las páginas van a tardar en empezar a cargar.")
    if not c:
        c.append(f"Todos los DNS resuelven «{nombre}» igual. Si no abre, el problema no es el DNS "
                 "(puede ser el sitio, un firewall o el navegador).")
    return c


def como_texto(d: dict) -> str:
    lineas = [f"Consulta DNS de {d['dominio']}"]
    for r in d["resultados"]:
        resp = ", ".join(r.get("ips", [])[:3]) if r["estado"] == "ok" else r["estado"]
        if r["estado"] == "no existe" and r.get("ttl_negativo") is not None:
            resp += f" (lo guarda {_minutos(r['ttl_negativo'])})"
        ms = f" · {r['ms']} ms" if r.get("ms") is not None else ""
        lineas.append(f"• {r['servidor']} ({r['quien']}): {resp}{ms}")
    lineas += ["", "Conclusión:"] + [f"• {c}" for c in d["conclusiones"]]
    return "\n".join(lineas)
