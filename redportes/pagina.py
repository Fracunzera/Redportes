"""«¿No abre una página?»: pruebas en cadena hasta encontrar la causa.

Orden (el mismo que seguiría un técnico) y se frena en la primera que falla:
1. ¿Anda Internet en general?  2. DNS  3. Archivo hosts  4. Puertos 443/80
5. HTTPS y certificado  6. Respuesta del sitio  7. MTU (solo si la conexión se queda colgada)
"""

from __future__ import annotations

import http.client
import re
import socket
import ssl
import time
from dataclasses import asdict, dataclass

from redportes import consulta_dns, diagnostico
from redportes.sistema import ES_MAC, ES_WINDOWS, ejecutar, tiene


@dataclass
class Paso:
    nombre: str
    estado: str          # ok | falla | aviso | omitido | info
    detalle: str = ""


class _Fin(Exception):
    """Se encontró la causa: cortar la cadena."""


# ---------------------------------------------------------------- pruebas sueltas

def conectar(ip: str, puerto: int, timeout: float = 5) -> tuple[bool, float | str]:
    inicio = time.monotonic()
    try:
        with socket.create_connection((ip, puerto), timeout=timeout):
            return True, round((time.monotonic() - inicio) * 1000)
    except socket.timeout:
        return False, "no responde (se agota el tiempo)"
    except ConnectionRefusedError:
        return False, "conexión rechazada"
    except OSError as e:
        return False, str(e)


_PROXIES = ("fortinet", "fortigate", "sophos", "palo alto", "zscaler", "kaspersky", "eset", "avast", "bitdefender",
            "mikrotik", "pfsense", "squid", "websense", "barracuda", "checkpoint", "watchguard", "netskope")


def emisor_certificado(dominio: str, ip: str, puerto: int = 443, timeout: float = 8) -> str:
    """Quién firmó el certificado que se recibe (sin validarlo), para detectar proxies que interceptan."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((ip, puerto), timeout=timeout) as s, \
                ctx.wrap_socket(s, server_hostname=dominio) as t:
            der = t.getpeercert(binary_form=True)
    except OSError:
        return ""
    # Sin dependencias: buscamos los textos imprimibles del emisor en el certificado DER.
    textos = re.findall(rb"[\x20-\x7e]{4,}", der or b"")
    return " ".join(t.decode() for t in textos[:12])


# Autoridades públicas que firman los sitios comunes. Si el certificado recibido viene de una de
# estas y aun así no valida, el problema es del equipo (certificados raíz o fecha), no de la red.
_CA_PUBLICAS = ("google trust services", "let's encrypt", "isrg", "digicert", "sectigo", "comodo",
                "globalsign", "amazon", "microsoft", "cloudflare", "entrust", "godaddy", "baltimore",
                "usertrust", "certum", "buypass", "zerossl", "actalis", "harica", "identrust")


def clasificar_certificado(dominio: str, ip: str = "") -> tuple[str, str]:
    """('publica' | 'proxy' | 'desconocido', nombre) según quién firmó el certificado recibido."""
    if not ip:
        try:
            ip = socket.getaddrinfo(dominio, 443, socket.AF_INET)[0][4][0]
        except OSError:
            return "desconocido", ""
    emisor = emisor_certificado(dominio, ip).lower()
    proxy = next((x for x in _PROXIES if x in emisor), "")
    if proxy:
        return "proxy", proxy.title()
    ca = next((x for x in _CA_PUBLICAS if x in emisor), "")
    if ca:
        return "publica", ca.title()
    return "desconocido", ""


def explicar_certificado(error: str, clase: str, nombre: str) -> tuple[str, list[str]]:
    """Veredicto y qué hacer cuando un certificado no valida."""
    e = error.lower()
    if clase == "proxy":
        return (f"Un equipo de la red ({nombre}) intercepta las conexiones seguras.",
                ["El firewall/antivirus reemplaza el certificado del sitio y este equipo no confía en él.",
                 "Hay que instalar su certificado en la PC o excluir el sitio de la inspección HTTPS."])
    if "expired" in e or "not yet valid" in e:
        return ("El certificado figura vencido (o todavía no válido).",
                ["Revisá primero la fecha y la hora de la PC: si están mal, todos los sitios dan este error.",
                 "Si la hora está bien, el certificado del sitio está vencido: avisale al dueño."])
    if clase == "publica":
        return (f"Este equipo no confía en certificados normales ({nombre}): le faltan los certificados raíz "
                "o tiene mal la fecha y hora.",
                ["Revisá la fecha y hora de la PC.",
                 "Actualizá el sistema (en Linux: el paquete ca-certificates).",
                 "No es un problema de la red: el sitio presenta un certificado válido."])
    return ("El certificado del sitio no es válido para esta dirección.",
            [f"Detalle: {error}.", "Revisá la fecha y hora de la PC; si están bien, es un problema del sitio o "
             "algo en la red lo intercepta."])


def probar_https(dominio: str, ip: str, timeout: float = 10) -> dict:
    """Handshake TLS validando el certificado y pedido HTTP. Lee hasta 256 KB para detectar cuelgues (MTU)."""
    ctx = ssl.create_default_context()
    inicio = time.monotonic()
    try:
        s = socket.create_connection((ip, 443), timeout=timeout)
    except OSError as e:
        return {"etapa": "conexion", "error": str(e)}
    try:
        t = ctx.wrap_socket(s, server_hostname=dominio)
    except ssl.SSLCertVerificationError as e:
        s.close()
        return {"etapa": "certificado", "error": e.verify_message or str(e), "codigo": e.verify_code}
    except (socket.timeout, TimeoutError):
        s.close()
        return {"etapa": "tls", "error": "colgado", "colgado": True}
    except (ssl.SSLError, OSError) as e:
        s.close()
        return {"etapa": "tls", "error": str(e)}
    try:
        c = http.client.HTTPSConnection(dominio, 443, timeout=timeout, context=ctx)
        c.sock = t
        c.request("GET", "/", headers={"User-Agent": "Mozilla/5.0 (Redportes)", "Accept": "text/html,*/*"})
        r = c.getresponse()
        leidos = 0
        while leidos < 262144:
            bloque = r.read(16384)
            if not bloque:
                break
            leidos += len(bloque)
        c.close()
    except (socket.timeout, TimeoutError):
        return {"etapa": "respuesta", "error": "colgado", "colgado": True}
    except (http.client.HTTPException, OSError) as e:
        return {"etapa": "respuesta", "error": str(e)}
    return {"etapa": "ok", "estado": r.status, "destino": r.getheader("Location", "") or "",
            "ms": round((time.monotonic() - inicio) * 1000), "bytes": leidos}


def probar_http(dominio: str, ip: str, timeout: float = 8) -> dict:
    try:
        c = http.client.HTTPConnection(ip, 80, timeout=timeout)
        c.request("GET", "/", headers={"Host": dominio, "User-Agent": "Mozilla/5.0 (Redportes)"})
        r = c.getresponse()
        r.read(65536)
        c.close()
        return {"estado": r.status, "destino": r.getheader("Location", "") or ""}
    except (http.client.HTTPException, OSError) as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- MTU

def _ping_df(ip: str, carga: int) -> str:
    """'ok', 'grande' (no entra sin fragmentar) o 'nada' (sin respuesta)."""
    if ES_WINDOWS:
        cmd = ["ping", "-f", "-l", str(carga), "-n", "1", "-w", "1500", ip]
    elif ES_MAC:
        cmd = ["ping", "-D", "-s", str(carga), "-c", "1", "-t", "2", ip]
    else:
        cmd = ["ping", "-M", "do", "-s", str(carga), "-c", "1", "-W", "2", ip]
    salida = ejecutar(cmd, timeout=6, encoding="oem").lower()
    if re.search(r"fragment|message too long|frag needed|demasiado largo|mtu", salida):
        return "grande"
    if re.search(r"ttl[=:]", salida):
        return "ok"
    return "nada"


def medir_mtu(ip: str) -> dict:
    """Busca el paquete más grande que llega sin fragmentar (búsqueda binaria entre 1200 y 1500)."""
    if not tiene("ping"):
        return {"estado": "sin_ping"}
    if _ping_df(ip, 1200 - 28) != "ok":
        return {"estado": "no_mide"}  # no responde ping: no se puede medir contra ese destino
    if _ping_df(ip, 1500 - 28) == "ok":
        return {"estado": "ok", "mtu": 1500}
    bajo, alto = 1200, 1500
    while alto - bajo > 1:
        medio = (bajo + alto) // 2
        if _ping_df(ip, medio - 28) == "ok":
            bajo = medio
        else:
            alto = medio
    return {"estado": "bajo", "mtu": bajo}


# ---------------------------------------------------------------- cadena

def investigar(texto: str, progreso=lambda m: None, medir_siempre_mtu: bool = False) -> dict:
    dominio = consulta_dns.limpiar(texto)
    if "." not in dominio:
        raise ValueError("Pegá la dirección de la página, por ejemplo www.ejemplo.com.ar")
    pasos: list[Paso] = []
    res = {"dominio": dominio, "veredicto": "", "estado": "ok", "que_hacer": [], "dns": None}

    def fin(estado, veredicto, que_hacer):
        res.update(estado=estado, veredicto=veredicto, que_hacer=que_hacer)
        raise _Fin

    nombres = ["Internet en general", "DNS", "Archivo hosts", "Conexión al sitio (puertos)",
               "HTTPS y certificado", "Respuesta del sitio", "MTU"]
    try:
        # 1. Referencia
        progreso("Probando si anda Internet…")
        ref = diagnostico.https()
        if ref.get("ok"):
            pasos.append(Paso(nombres[0], "ok", f"google.com responde ({ref['ms']} ms)"))
        elif conectar("1.1.1.1", 443, timeout=4)[0]:
            # Internet anda: lo que falla es abrir por nombre (DNS). Seguimos para confirmarlo.
            pasos.append(Paso(nombres[0], "aviso", "hay salida a Internet, pero google.com no abre por nombre"))
        else:
            pasos.append(Paso(nombres[0], "falla", f"google.com tampoco abre: {ref.get('error')}"))
            fin("falla", "No es la página: no anda Internet en esta PC.",
                ["Usá «Probar mi conexión» para ver si falla el Wi-Fi/cable, el router o el proveedor."])

        # 2. DNS
        progreso(f"Consultando {dominio} en los DNS…")
        dns = consulta_dns.comparar(dominio)
        res["dns"] = dns
        pc = [r for r in dns["resultados"] if r["de_la_pc"]]
        pub_ok = [r for r in dns["resultados"] if not r["de_la_pc"] and r["estado"] == "ok"]
        pub_todos_no = all(r["estado"] == "no existe" for r in dns["resultados"] if not r["de_la_pc"])
        try:
            ip_sistema = socket.getaddrinfo(dominio, 443, socket.AF_INET)[0][4][0]
        except OSError:
            ip_sistema = ""
        if pub_todos_no:
            pasos.append(Paso(nombres[1], "falla", "ningún DNS la encuentra"))
            fin("falla", f"La dirección «{dominio}» no existe.",
                ["Revisá que esté bien escrita.", "Si es un sitio tuyo, revisá que el registro DNS esté cargado."])
        malos = [r for r in pc if r["estado"] in ("no existe", "bloqueado", "sin respuesta", "error",
                                                    "falla del servidor", "rechazada")]
        if malos and pub_ok:
            m = malos[0]
            if m["estado"] == "no existe":
                espera = consulta_dns._minutos(m.get("ttl_negativo"))
                pasos.append(Paso(nombres[1], "falla", f"el DNS de la PC ({m['servidor']}) dice que no existe; "
                                                       f"{pub_ok[0]['quien'].split(' ')[0]} sí la encuentra"))
                fin("falla", "El DNS de esta PC tiene guardada una respuesta vieja."
                    + (f" La va a seguir dando {espera} más." if espera else ""),
                    ["Para entrar ya: cambiá el DNS de la PC o del router a 1.1.1.1 u 8.8.8.8.",
                     "O probá con datos móviles, o reiniciá el router (vacía su caché).",
                     "En Windows también ayuda: ipconfig /flushdns"])
            if m["estado"] == "bloqueado":
                pasos.append(Paso(nombres[1], "falla", f"el DNS de la PC ({m['servidor']}) la bloquea (0.0.0.0)"))
                fin("falla", "La página está bloqueada por el DNS de esta red.",
                    [f"El servidor {m['servidor']} la filtra: puede ser AdGuard, Pi-hole o el firewall.",
                     "Si tiene que abrir, agregala a la lista de permitidos de ese filtro."])
            pasos.append(Paso(nombres[1], "falla", f"el DNS de la PC ({m['servidor']}) {m['estado']}"))
            fin("falla", "El DNS de esta PC no está respondiendo bien.",
                [f"El servidor {m['servidor']} {m['estado']}. Revisalo o cambiá el DNS a 1.1.1.1 / 8.8.8.8."])
        if not ip_sistema:
            ip_sistema = pub_ok[0]["ips"][0] if pub_ok else ""
            if not ip_sistema:
                pasos.append(Paso(nombres[1], "falla", "no se pudo obtener la dirección del sitio"))
                fin("falla", "No se pudo averiguar la dirección del sitio.", ["Revisá el DNS de la PC."])
        pasos.append(Paso(nombres[1], "ok", f"{dominio} → {ip_sistema}"))

        # 3. hosts
        from redportes.equipo_local import hosts

        en_hosts = [h for h in hosts() if dominio in h.split()[1:]]
        conocidas = {ip for r in dns["resultados"] for ip in r.get("ips", [])}
        if en_hosts:
            ip_hosts = en_hosts[0].split()[0]
            if ip_hosts in ("0.0.0.0", "127.0.0.1"):
                pasos.append(Paso(nombres[2], "falla", en_hosts[0]))
                fin("falla", "El archivo hosts de esta PC bloquea la página.",
                    ["Sacá la línea «" + en_hosts[0] + "» del archivo hosts "
                     "(en Windows: C:\\Windows\\System32\\drivers\\etc\\hosts, como administrador)."])
            pasos.append(Paso(nombres[2], "aviso", f"redirige a {ip_hosts} ({en_hosts[0]})"))
            ip_sistema = ip_hosts
        else:
            pasos.append(Paso(nombres[2], "ok", "sin entradas para este sitio"))

        # 4. Puertos
        progreso(f"Conectando a {ip_sistema}…")
        ok443, d443 = conectar(ip_sistema, 443)
        ok80, d80 = conectar(ip_sistema, 80) if not ok443 else (None, "")
        if ok443:
            pasos.append(Paso(nombres[3], "ok", f"puerto 443 abierto ({d443} ms)"))
        elif ok80:
            pasos.append(Paso(nombres[3], "aviso", f"solo responde el puerto 80 (443: {d443})"))
        else:
            pasos.append(Paso(nombres[3], "falla", f"443: {d443} · 80: {d80}"))
            otra = [ip for ip in conocidas if ip != ip_sistema]
            fin("falla", "La PC encuentra el sitio pero no puede conectarse.",
                ["El sitio puede estar caído, o un firewall (de la red o del proveedor) lo bloquea.",
                 "Probá desde el celular con datos: si ahí abre, el bloqueo está en esta red."]
                + ([f"Otros DNS dan otra dirección ({otra[0]}): si el sitio se mudó, puede ser caché vieja."]
                   if otra else []))

        # 5 y 6. HTTPS, certificado y respuesta
        sospecha_mtu = False
        if ok443:
            progreso("Probando HTTPS…")
            h = probar_https(dominio, ip_sistema)
            if h["etapa"] == "certificado":
                clase, nombre = clasificar_certificado(dominio, ip_sistema)
                pasos.append(Paso(nombres[4], "falla", h["error"]))
                veredicto, hacer = explicar_certificado(h["error"], clase, nombre)
                fin("falla", veredicto, hacer)
            if h["etapa"] in ("tls", "respuesta") and h.get("colgado"):
                pasos.append(Paso(nombres[4] if h["etapa"] == "tls" else nombres[5], "falla",
                                  "conecta pero se queda colgado"))
                sospecha_mtu = True
            elif h["etapa"] in ("tls", "conexion"):
                pasos.append(Paso(nombres[4], "falla", h["error"]))
                fin("falla", "No se pudo establecer la conexión segura con el sitio.",
                    [f"Detalle: {h['error']}.", "Puede ser un proxy/firewall de la red o un problema del sitio."])
            elif h["etapa"] == "respuesta":
                pasos.append(Paso(nombres[4], "ok", "certificado válido"))
                pasos.append(Paso(nombres[5], "falla", h["error"]))
                fin("falla", "El sitio corta la conexión al pedir la página.",
                    [f"Detalle: {h['error']}.", "Suele ser un problema del sitio o un filtro de la red."])
            else:
                pasos.append(Paso(nombres[4], "ok", "certificado válido"))
                st = h["estado"]
                if st >= 500:
                    pasos.append(Paso(nombres[5], "falla", f"error {st} del servidor"))
                    fin("falla", f"El sitio está con problemas (error {st}).",
                        ["Es del lado del sitio: no se arregla desde esta red. Probá más tarde o avisale al dueño."])
                if st in (401, 403, 451):
                    pasos.append(Paso(nombres[5], "aviso", f"responde {st}: acceso denegado"))
                    fin("aviso", "El sitio responde, pero no deja entrar desde aquí.",
                        ["Puede bloquear por país o por IP (pasa con CGNAT, VPN o IPs compartidas), o pedir login.",
                         "Probá desde otra conexión para confirmarlo."])
                destino = f" → redirige a {h['destino']}" if h.get("destino") else ""
                pasos.append(Paso(nombres[5], "ok", f"responde {st} en {h['ms']} ms{destino}"))
        else:
            p = probar_http(dominio, ip_sistema)
            pasos.append(Paso(nombres[4], "aviso", "el sitio no tiene HTTPS"))
            if "error" in p:
                pasos.append(Paso(nombres[5], "falla", p["error"]))
                fin("falla", "El sitio no responde la página.", [p["error"]])
            pasos.append(Paso(nombres[5], "ok", f"responde {p['estado']} por HTTP"))

        # 7. MTU
        if sospecha_mtu or medir_siempre_mtu:
            progreso("Midiendo el MTU…")
            m = medir_mtu(ip_sistema)
            if m["estado"] == "no_mide":
                m = medir_mtu("8.8.8.8")
            if m["estado"] == "bajo":
                pasos.append(Paso(nombres[6], "falla", f"pasan paquetes de hasta {m['mtu']} bytes (lo normal es 1500)"))
                fin("falla", f"Problema de MTU: en el camino solo pasan paquetes de {m['mtu']} bytes.",
                    ["Por eso las páginas «se quedan cargando»: los paquetes grandes se pierden.",
                     "En el router MikroTik: /ip firewall mangle add chain=forward protocol=tcp tcp-flags=syn "
                     "action=change-mss new-mss=clamp-to-pmtu passthrough=yes",
                     f"O en la PC (Windows, como administrador): netsh interface ipv4 set subinterface "
                     f"\"Ethernet\" mtu={m['mtu']} store=persistent"])
            if m["estado"] == "ok":
                pasos.append(Paso(nombres[6], "ok", "pasan paquetes de 1500 bytes"))
            else:
                pasos.append(Paso(nombres[6], "info", "no se pudo medir (el ping está bloqueado)"))
            if sospecha_mtu:
                fin("falla", "El sitio acepta la conexión pero no termina de responder.",
                    ["Puede ser un filtro que corta la conexión, un proxy, o el sitio sobrecargado.",
                     "Probá desde otra conexión (datos móviles) para saber si es esta red."])
        else:
            pasos.append(Paso(nombres[6], "omitido", "no hizo falta (la página cargó completa)"))

        fin("ok", f"Desde esta PC, «{dominio}» abre bien.",
            ["Si en el navegador no abre: probá en una ventana de incógnito y vaciá la caché del navegador.",
             "Revisá extensiones, antivirus o un proxy configurado en el navegador.",
             "Si a otra persona no le abre, el problema está en su conexión (muchas veces, el DNS)."])
    except _Fin:
        pass
    hechos = {p.nombre for p in pasos}
    for n in nombres:
        if n not in hechos:
            pasos.append(Paso(n, "omitido", "no se probó (la causa ya apareció antes)"))
    res["pasos"] = [asdict(p) for p in pasos]
    return res


ICONO = {"ok": "✅", "falla": "❌", "aviso": "⚠️", "omitido": "·", "info": "ℹ️"}


def como_texto(r: dict) -> str:
    lineas = [f"¿Por qué no abre {r['dominio']}?", "", r["veredicto"]]
    lineas += [f"  - {q}" for q in r["que_hacer"]]
    lineas += [""] + [f"{ICONO[p['estado']]} {p['nombre']}: {p['detalle']}" for p in r["pasos"]]
    return "\n".join(lineas)
