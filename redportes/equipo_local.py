"""Configuración del equipo desde el que se escanea: red, Wi-Fi, sistema y ajustes que suelen dar problemas.

Solo lectura: no cambia nada y no necesita permisos de administrador.
"""

from __future__ import annotations

import ipaddress
import os
import platform
import re
import shutil
import socket
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import psutil

from redportes.red import listar_interfaces, puerta_de_enlace, servidores_dns
from redportes.sistema import ES_MAC, ES_WINDOWS, ejecutar, tiene

_IPV4 = r"(?:\d{1,3}\.){3}\d{1,3}"


def _norm(texto: str) -> str:
    """Minúsculas y sin acentos, para reconocer claves en inglés o castellano."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def _si(valor: str) -> bool:
    return _norm(valor) in ("yes", "si", "s", "true", "activado", "habilitado")


# ---------------------------------------------------------------- Wi-Fi

_CLAVES_NETSH = {
    "ssid": "ssid", "bssid": "bssid", "radio type": "estandar", "tipo de radio": "estandar",
    "authentication": "seguridad", "autenticacion": "seguridad", "cipher": "cifrado", "cifrado": "cifrado",
    "band": "banda", "banda": "banda", "channel": "canal", "canal": "canal",
    "receive rate (mbps)": "recepcion", "velocidad de recepcion (mbps)": "recepcion",
    "transmit rate (mbps)": "transmision", "velocidad de transmision (mbps)": "transmision",
    "signal": "senal", "senal": "senal", "state": "estado", "estado": "estado",
    "name": "interfaz", "nombre": "interfaz", "description": "adaptador", "descripcion": "adaptador",
}


def parsear_netsh_wlan(texto: str) -> dict:
    """Salida de `netsh wlan show interfaces` (inglés o castellano). Toma la interfaz conectada."""
    bloques, actual = [], {}
    for linea in texto.splitlines():
        if ":" not in linea:
            if actual:
                bloques.append(actual)
                actual = {}
            continue
        clave, valor = linea.split(":", 1)
        campo = _CLAVES_NETSH.get(_norm(clave))
        if campo == "interfaz" and "interfaz" in actual:
            bloques.append(actual)
            actual = {}
        if campo and campo not in actual:
            actual[campo] = valor.strip()
    if actual:
        bloques.append(actual)
    conectados = [b for b in bloques if b.get("ssid")]
    if not conectados:
        return {}
    w = conectados[0]
    if w.get("senal"):
        m = re.search(r"\d+", w["senal"])
        w["senal"] = int(m.group()) if m else None
    if w.get("canal", "").isdigit():
        w["canal"] = int(w["canal"])
    if not w.get("banda") and isinstance(w.get("canal"), int):
        w["banda"] = "2,4 GHz" if w["canal"] <= 14 else "5 GHz"
    return w


def parsear_nmcli_wifi(texto: str) -> dict:
    """`nmcli -t -f ACTIVE,SSID,CHAN,RATE,SIGNAL,SECURITY,BSSID,DEVICE dev wifi`."""
    for linea in texto.splitlines():
        campos = re.split(r"(?<!\\):", linea)
        if len(campos) >= 7 and _si(campos[0]):
            campos = [c.replace("\\:", ":") for c in campos]
            canal = int(campos[2]) if campos[2].isdigit() else None
            return {
                "ssid": campos[1], "canal": canal, "recepcion": campos[3].split()[0] if campos[3] else "",
                "senal": int(campos[4]) if campos[4].isdigit() else None,
                "seguridad": campos[5] or "abierta", "bssid": campos[6],
                "interfaz": campos[7] if len(campos) > 7 else "",
                "banda": ("2,4 GHz" if canal <= 14 else "5 GHz") if canal else "",
            }
    return {}


def wifi() -> dict:
    if ES_WINDOWS:
        return parsear_netsh_wlan(ejecutar(["netsh", "wlan", "show", "interfaces"], encoding="oem"))
    if tiene("nmcli"):
        return parsear_nmcli_wifi(ejecutar(
            ["nmcli", "-t", "-f", "ACTIVE,SSID,CHAN,RATE,SIGNAL,SECURITY,BSSID,DEVICE", "dev", "wifi"]))
    return {}


# ---------------------------------------------------------------- DHCP

def parsear_ipconfig_dhcp(texto: str, ip: str) -> dict:
    """De `ipconfig /all`: si el adaptador que tiene la IP usa DHCP y qué servidor la dio."""
    bloques = re.split(r"\n(?=\S)", texto.replace("\r", ""))
    for b in bloques:
        if not re.search(rf"\b{re.escape(ip)}\b", b):
            continue
        res = {}
        for linea in b.splitlines():
            if ":" not in linea:
                continue
            clave, valor = linea.split(":", 1)
            c = _norm(clave.replace(".", " "))
            if c.startswith(("dhcp enabled", "dhcp habilitado")):
                res["dhcp"] = _si(valor)
            elif c.startswith(("dhcp server", "servidor dhcp")):
                m = re.search(_IPV4, valor)
                res["servidor_dhcp"] = m.group() if m else ""
            elif c.startswith(("lease expires", "la concesion expira", "concesion expira")):
                res["vence"] = valor.strip()
        return res
    return {}


def parsear_ip_addr(texto: str, ip: str) -> dict:
    """`ip -4 -o addr`: la palabra 'dynamic' indica que la dirección vino por DHCP."""
    for linea in texto.splitlines():
        if f"inet {ip}/" in linea:
            return {"dhcp": " dynamic " in f" {linea} "}
    return {}


def dhcp(ip: str) -> dict:
    if ES_WINDOWS:
        return parsear_ipconfig_dhcp(ejecutar(["ipconfig", "/all"], encoding="oem"), ip)
    if tiene("ip"):
        return parsear_ip_addr(ejecutar(["ip", "-4", "-o", "addr"]), ip)
    return {}


# ---------------------------------------------------------------- otros ajustes

def proxy() -> str:
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if os.environ.get(var):
            return os.environ[var]
    if ES_WINDOWS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
                activo = winreg.QueryValueEx(k, "ProxyEnable")[0]
                if activo:
                    return winreg.QueryValueEx(k, "ProxyServer")[0]
                try:
                    return "configuración automática: " + winreg.QueryValueEx(k, "AutoConfigURL")[0]
                except OSError:
                    pass
        except OSError:
            pass
    return ""


def parsear_firewall_windows(texto: str) -> dict:
    """`netsh advfirewall show allprofiles state`: cuántos perfiles están activos."""
    estados = []
    for linea in texto.splitlines():
        partes = linea.split()
        if len(partes) >= 2 and _norm(partes[0]) in ("state", "estado"):
            estados.append(_norm(partes[-1]) in ("on", "activar", "activado", "activo"))
    if not estados:
        return {}
    return {"perfiles": len(estados), "activos": sum(estados)}


def firewall() -> dict:
    if ES_WINDOWS:
        return parsear_firewall_windows(ejecutar(["netsh", "advfirewall", "show", "allprofiles", "state"],
                                                 encoding="oem"))
    return {}


def entradas_hosts(texto: str) -> list[str]:
    """Entradas del archivo hosts que no son las de fábrica (localhost)."""
    res = []
    for linea in texto.splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        partes = linea.split()
        if len(partes) < 2:
            continue
        nombres = [n for n in partes[1:] if not n.startswith(("localhost", "ip6-")) and n != "broadcasthost"]
        if nombres and partes[0] not in ("::1", "fe00::0", "ff00::0", "ff02::1", "ff02::2"):
            res.append(f"{partes[0]} {' '.join(nombres)}")
    return res


def hosts() -> list[str]:
    ruta = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
            if ES_WINDOWS else Path("/etc/hosts"))
    try:
        texto = ruta.read_text(errors="replace")
    except OSError:
        return []
    nombre = socket.gethostname().lower()
    return [h for h in entradas_hosts(texto) if nombre not in h.lower() and not h.startswith("127.0.1.1")]


# ---------------------------------------------------------------- sistema

def sistema() -> dict:
    if ES_WINDOWS:
        version = f"Windows {platform.release()} (compilación {platform.version()})"
    elif ES_MAC:
        version = f"macOS {platform.mac_ver()[0]}"
    else:
        version = platform.platform()
        try:
            for linea in Path("/etc/os-release").read_text().splitlines():
                if linea.startswith("PRETTY_NAME="):
                    version = linea.split("=", 1)[1].strip('"')
        except OSError:
            pass
    mem = psutil.virtual_memory()
    raiz = os.environ.get("SystemDrive", "C:") + "\\" if ES_WINDOWS else "/"
    disco = shutil.disk_usage(raiz)
    horas = (time.time() - psutil.boot_time()) / 3600
    return {
        "nombre": socket.gethostname(), "version": version, "arquitectura": platform.machine(),
        "encendido_horas": round(horas, 1), "cpus": psutil.cpu_count(),
        "ram_gb": round(mem.total / 2**30, 1), "ram_uso": round(mem.percent),
        "disco_libre_gb": round(disco.free / 2**30, 1), "disco_uso": round(100 * disco.used / disco.total),
    }


# ---------------------------------------------------------------- todo junto

def _tipo_interfaz(nombre: str, es_wifi: bool) -> str:
    n = nombre.lower()
    if es_wifi or any(x in n for x in ("wi-fi", "wifi", "wlan", "wireless", "inalámbrica", "wlp")):
        return "Wi-Fi"
    if any(x in n for x in ("ethernet", "eth", "enp", "eno", "ens", "lan")):
        return "Cable (Ethernet)"
    return "Otra"


def recolectar() -> dict:
    estados = psutil.net_if_stats()
    w = wifi()
    gw = puerta_de_enlace()
    interfaces = []
    for itf in listar_interfaces():
        st = estados.get(itf.nombre)
        es_wifi = bool(w) and (w.get("interfaz") == itf.nombre)
        dato = {
            "nombre": itf.nombre, "tipo": _tipo_interfaz(itf.nombre, es_wifi), "ip": itf.ip,
            "mascara": itf.mascara, "red": itf.red, "mac": itf.mac or "", "virtual": itf.virtual,
            "velocidad_mbps": st.speed if st and st.speed else None,
            "duplex": {psutil.NIC_DUPLEX_FULL: "completo", psutil.NIC_DUPLEX_HALF: "medio"}.get(
                st.duplex, "") if st else "",
            "mtu": st.mtu if st else None,
            "principal": False,
        }
        dato.update(dhcp(itf.ip))
        interfaces.append(dato)
    if interfaces:
        principal = next((i for i in interfaces if gw and ipaddress.IPv4Address(gw) in
                          ipaddress.IPv4Network(i["red"])), interfaces[0])
        principal["principal"] = True
    res = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "sistema": sistema(), "interfaces": interfaces, "wifi": w, "puerta": gw,
        "dns": servidores_dns(), "proxy": proxy(), "firewall": firewall(), "hosts": hosts(),
    }
    res["observaciones"] = observaciones(res)
    return res


def observaciones(d: dict) -> list[dict]:
    obs = []

    def o(estado, texto):
        obs.append({"estado": estado, "texto": texto})

    principal = next((i for i in d["interfaces"] if i.get("principal")), None)
    if not d["interfaces"]:
        o("falla", "No hay ninguna interfaz de red con IP.")
    if not d.get("puerta"):
        o("falla", "No hay puerta de enlace: el equipo no puede salir de su red.")
    for i in d["interfaces"]:
        if i["ip"].startswith("169.254."):
            o("falla", f"{i['nombre']} tiene una IP automática (169.254.x.x): no le llegó respuesta del DHCP.")
        if i["tipo"].startswith("Cable") and i.get("velocidad_mbps") in (10, 100) and not i["virtual"]:
            o("aviso", f"{i['nombre']} está conectada a {i['velocidad_mbps']} Mb/s: si el switch es gigabit, "
                       "revisar el cable (puede tener un par cortado) o el puerto.")
        if i.get("duplex") == "medio":
            o("aviso", f"{i['nombre']} está en medio dúplex: suele causar lentitud y errores; revisar la "
                       "negociación en el switch.")
        if i.get("mtu") and i["mtu"] < 1500 and not i["virtual"] and i["tipo"] != "Otra":
            o("info", f"{i['nombre']} tiene MTU {i['mtu']} (menor a 1500).")
    if principal and principal.get("dhcp") is False:
        o("info", f"La IP {principal['ip']} está fija (no viene por DHCP): verificar que esté fuera del "
                  "rango del DHCP para evitar conflictos.")
    w = d.get("wifi") or {}
    if w:
        senal = w.get("senal")
        if isinstance(senal, int) and senal < 50:
            o("aviso", f"Señal Wi-Fi débil ({senal}%): acercarse al punto de acceso o sumar uno; "
                       "con menos de 50% hay cortes y lentitud.")
        seg = _norm(w.get("seguridad") or "")
        if seg in ("open", "abierta", "abierto", "--", "") or "wep" in seg:
            o("falla", f"La red Wi-Fi «{w.get('ssid')}» es abierta o usa WEP: cualquiera puede conectarse "
                       "o descifrar el tráfico. Usar WPA2 o WPA3.")
        elif "wpa3" not in seg and "wpa2" not in seg and "wpa" in seg:
            o("aviso", f"La red Wi-Fi usa {w.get('seguridad')}: pasar a WPA2 o WPA3.")
        canal = w.get("canal")
        if isinstance(canal, int) and canal <= 14 and canal not in (1, 6, 11):
            o("info", f"El Wi-Fi está en el canal {canal} de 2,4 GHz: los canales 1, 6 u 11 evitan "
                      "superponerse con las redes vecinas.")
        if isinstance(canal, int) and canal <= 14 and principal and principal["tipo"] == "Wi-Fi":
            o("info", "El equipo está conectado en 2,4 GHz: si el router tiene 5 GHz, suele ser más rápido "
                      "y con menos interferencia.")
    if d.get("proxy"):
        o("info", f"Hay un proxy configurado ({d['proxy']}): si algunas páginas no cargan, revisarlo.")
    fw = d.get("firewall") or {}
    if fw and fw["activos"] < fw["perfiles"]:
        o("aviso", f"El firewall de Windows está desactivado en {fw['perfiles'] - fw['activos']} de "
                   f"{fw['perfiles']} perfiles.")
    if d.get("hosts"):
        o("info", f"El archivo hosts tiene {len(d['hosts'])} entrada(s) agregada(s): pueden redirigir o "
                  "bloquear sitios. Revisarlas si algo no abre o abre otra cosa.")
    sis = d.get("sistema") or {}
    if sis.get("disco_uso", 0) >= 90:
        o("aviso", f"El disco está al {sis['disco_uso']}%: con poco espacio Windows se vuelve lento y "
                   "fallan las actualizaciones.")
    if sis.get("encendido_horas", 0) > 24 * 14:
        o("info", f"El equipo lleva {round(sis['encendido_horas'] / 24)} días encendido sin reiniciar.")
    if not obs:
        o("ok", "No se ve nada raro en la configuración de este equipo.")
    return obs


def como_texto(d: dict) -> str:
    s = d["sistema"]
    lineas = [f"Equipo {s['nombre']} — {s['version']}",
              f"RAM {s['ram_gb']} GB ({s['ram_uso']}% en uso) · disco libre {s['disco_libre_gb']} GB · "
              f"encendido hace {s['encendido_horas']} h", ""]
    for i in d["interfaces"]:
        if i["virtual"]:
            continue
        extra = []
        if i.get("velocidad_mbps"):
            extra.append(f"{i['velocidad_mbps']} Mb/s")
        if "dhcp" in i:
            extra.append("DHCP" + (f" de {i['servidor_dhcp']}" if i.get("servidor_dhcp") else "")
                         if i["dhcp"] else "IP fija")
        lineas.append(f"{i['nombre']} ({i['tipo']}): {i['ip']}/{i['red'].split('/')[1]} · MAC {i['mac']}"
                      + (f" · {' · '.join(extra)}" if extra else ""))
    lineas.append(f"Puerta de enlace: {d.get('puerta') or '—'} · DNS: {', '.join(d.get('dns') or []) or '—'}")
    w = d.get("wifi") or {}
    if w:
        lineas.append(f"Wi-Fi «{w.get('ssid')}»: señal {w.get('senal')}% · canal {w.get('canal')} "
                      f"({w.get('banda', '')}) · {w.get('estandar', '')} · {w.get('seguridad', '')} · "
                      f"{w.get('recepcion', '')} Mb/s")
    if d.get("proxy"):
        lineas.append(f"Proxy: {d['proxy']}")
    lineas += ["", "Observaciones:"] + [f"• {x['texto']}" for x in d["observaciones"]]
    return "\n".join(lineas)
