"""Adivina qué es cada equipo a partir de fabricante, puertos, TTL y banners."""

from __future__ import annotations

from redportes.modelo import Equipo
from redportes.oui import mac_aleatoria

CAMARAS = ("hikvision", "dahua", "axis", "uniview", "ezviz", "hanwha", "vivotek", "imou",
           "reolink", "zhejiang uniview", "tiandy")
IMPRESORAS = ("hewlett", "hp inc", "epson", "seiko epson", "brother", "canon", "lexmark", "ricoh",
              "kyocera", "xerox", "konica", "sharp", "oki")
TELEFONOS_IP = ("grandstream", "yealink", "fanvil", "polycom", "snom", "htek", "siemens")
VIRTUALES = ("vmware", "virtualbox", "qemu", "proxmox", "hyper-v", "xen")
MOVILES = ("apple", "samsung", "xiaomi", "motorola", "huawei", "oppo", "vivo", "realme", "oneplus",
           "google", "honor")
TVS = ("gaoshengda", "tcl", "hisense", "roku", "skyworth", "amlogic", "vizio", "noblex", "bgh",
       "xiaomi communications")
# Aplicaciones reconocibles por el título de su web: (palabra clave, nombre, tipo)
APPS = (
    ("adguard", "AdGuard Home", "Servidor DNS"), ("pi-hole", "Pi-hole", "Servidor DNS"),
    ("home assistant", "Home Assistant", "Domótica"), ("octoprint", "OctoPrint", "Impresora 3D"),
    ("unifi", "UniFi", "Controlador UniFi"), ("proxmox", "Proxmox VE", "Servidor Proxmox"),
    ("nextcloud", "Nextcloud", "Servidor de archivos"), ("truenas", "TrueNAS", "NAS"),
    ("synology", "Synology", "NAS"), ("qnap", "QNAP", "NAS"), ("openmediavault", "OpenMediaVault", "NAS"),
    ("zabbix", "Zabbix", "Monitoreo"), ("grafana", "Grafana", "Monitoreo"),
    ("portainer", "Portainer", "Servidor Docker"), ("jellyfin", "Jellyfin", "Servidor multimedia"),
    ("plex", "Plex", "Servidor multimedia"), ("routeros", "RouterOS", "MikroTik"),
    ("pfsense", "pfSense", "Firewall"), ("opnsense", "OPNsense", "Firewall"),
)


def aplicaciones(e: Equipo) -> list[tuple[str, str]]:
    titulos = " ".join(p.titulo for p in e.puertos).lower()
    return [(nombre, tipo) for clave, nombre, tipo in APPS if clave in titulos]


RED = ("cisco", "tp-link", "tplink", "d-link", "netgear", "aruba", "ruckus", "zyxel", "juniper",
       "fortinet", "huawei technologies", "tenda", "mercusys")


def _tiene(fab: str, lista) -> bool:
    return any(x in fab for x in lista)


def sistema_por_ttl(ttl: int | None) -> str:
    if ttl is None:
        return ""
    if ttl <= 64:
        return "Linux/Unix (por TTL)"
    if ttl <= 128:
        return "Windows (por TTL)"
    return "Equipo de red / embebido (por TTL)"


def sistema_por_banners(e: Equipo) -> str:
    texto = " ".join(p.banner + " " + p.titulo for p in e.puertos).lower()
    if "rosssh" in texto or "routeros" in texto or "mikrotik" in texto:
        return "MikroTik RouterOS"
    for distro in ("ubuntu", "debian", "raspbian", "centos", "red hat", "fedora", "freebsd"):
        if distro in texto:
            return distro.title() if distro != "freebsd" else "FreeBSD"
    if "proxmox" in texto:
        return "Proxmox VE"
    if 3389 in e.abiertos() or {135, 445} <= e.abiertos():
        return "Windows"
    return ""


def clasificar(e: Equipo) -> None:
    fab = (e.fabricante or "").lower()
    p = e.abiertos()
    e.sistema = sistema_por_banners(e)
    if not e.sistema and "mikrotik" in fab:
        e.sistema = "MikroTik RouterOS (probable)"
    e.sistema = e.sistema or sistema_por_ttl(e.ttl)

    apps = aplicaciones(e)
    upnp = " ".join(e.upnp)
    if e.es_este_equipo:
        e.tipo = "Este equipo"
    elif e.es_puerta:
        e.tipo = "Router (puerta de enlace)"
    elif _tiene(fab, CAMARAS) or 37777 in p:
        e.tipo = "Cámara IP / grabador"
    elif "mikrotik" in fab or 8291 in p or "RouterOS" in e.sistema:
        e.tipo = "MikroTik"
    elif "ubiquiti" in fab:
        e.tipo = "Ubiquiti (AP / antena)"
    elif 554 in p:
        e.tipo = "Cámara IP / grabador"
    elif _tiene(fab, IMPRESORAS) or p & {9100, 515, 631}:
        e.tipo = "Impresora"
    elif _tiene(fab, TELEFONOS_IP) or 5060 in p:
        e.tipo = "Teléfono IP / central"
    elif 8006 in p or e.sistema == "Proxmox VE":
        e.tipo = "Servidor Proxmox"
    elif apps:
        e.tipo = f"{apps[0][1]} ({', '.join(n for n, _ in apps)})"
    elif _tiene(fab, VIRTUALES):
        e.tipo = "Máquina virtual"
    elif "raspberry" in fab:
        e.tipo = "Raspberry Pi"
    elif e.sistema == "Windows" or (e.sistema.startswith("Windows") and p):
        e.tipo = "PC / servidor Windows"
    elif _tiene(fab, RED):
        e.tipo = "Equipo de red"
    elif 22 in p and e.sistema:
        e.tipo = "Servidor / equipo Linux"
    elif _tiene(fab, TVS) or "MediaRenderer" in upnp:
        e.tipo = "Smart TV / TV box (probable)"
    elif mac_aleatoria(e.mac):
        e.tipo = "Celular o notebook (MAC aleatoria)"
    elif _tiene(fab, MOVILES) and not p:
        e.tipo = "Celular / tablet (probable)"
    elif e.sistema.startswith("Windows"):
        e.tipo = "PC Windows (probable)"
    else:
        e.tipo = "Desconocido"
