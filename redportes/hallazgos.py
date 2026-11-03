"""Cosas que conviene revisar, explicadas en castellano y con qué hacer."""

from __future__ import annotations

from redportes.modelo import Equipo, Hallazgo
from redportes.upnp import es_igd

_WEB_PLANA = {80, 5000, 8000, 8080, 8081}
_BASES = {3306: "MySQL", 1433: "SQL Server", 5432: "PostgreSQL", 6379: "Redis", 27017: "MongoDB"}


def evaluar(e: Equipo) -> list[Hallazgo]:
    p = e.abiertos()
    h: list[Hallazgo] = []

    def agregar(nivel, titulo, que_es, que_hacer, puerto=None, detalle=""):
        if not detalle and puerto:
            detalle = f"puerto {puerto}"
        h.append(Hallazgo(nivel, titulo, que_es, que_hacer, e.ip, puerto, detalle))

    if 23 in p:
        agregar("alto", "Telnet abierto",
                "Telnet manda usuario, contraseña y todo lo que se escribe sin cifrar. Cualquiera "
                "en la red puede leerlo.",
                "Desactivar Telnet y administrar el equipo por SSH o por la web con HTTPS.", 23)
    if e.smbv1:
        agregar("alto", "Acepta SMBv1",
                "SMBv1 es la versión vieja de carpetas compartidas de Windows. Es la que usaron "
                "WannaCry y otros ransomware para propagarse solos por la red.",
                "Desactivar SMBv1 (en Windows: 'Activar o desactivar características' → quitar "
                "'Compatibilidad con SMB 1.0'). Si es un NAS o impresora vieja, actualizar firmware "
                "o configurar SMB2/3 como mínimo.", 445)
    if 21 in p:
        agregar("medio", "FTP sin cifrar",
                "FTP manda usuario y contraseña en texto plano.",
                "Usar SFTP o FTPS. Si solo lo usa un escáner o una cámara, limitarlo a esa IP.", 21)
    if 8728 in p:
        agregar("medio", "API de MikroTik sin cifrar",
                "El puerto 8728 es la API de RouterOS sin cifrado.",
                "Si no se usa: /ip service disable api. Si se usa, pasar a api-ssl (8729) y "
                "restringir 'address' a las IP de administración.", 8728)
    if 8291 in p:
        agregar("bajo", "Winbox accesible",
                "Winbox está abierto para toda la red local.",
                "Restringir con /ip service set winbox address=<red de administración> y mantener "
                "RouterOS actualizado.", 8291)
    if 1723 in p:
        agregar("medio", "VPN PPTP",
                "PPTP usa un cifrado que se rompe fácilmente.",
                "Migrar a WireGuard, IKEv2 o OpenVPN.", 1723)
    if 3389 in p:
        agregar("medio", "Escritorio remoto (RDP) abierto",
                "Normal en una red interna, pero es la puerta de entrada más común de ransomware si "
                "llega a quedar publicado a Internet.",
                "Confirmar que no esté redirigido en el router, exigir NLA y contraseñas fuertes. "
                "Para acceso desde afuera, usar VPN.", 3389)
    if 5900 in p:
        agregar("medio", "VNC abierto",
                "VNC muchas veces no cifra y suele tener contraseñas cortas.",
                "Restringir a la red de administración o tunelizar por SSH/VPN.", 5900)
    for puerto, nombre in _BASES.items():
        if puerto in p:
            agregar("medio", f"Base de datos {nombre} accesible por red",
                    f"{nombre} acepta conexiones desde otros equipos de la red.",
                    "Si solo la usa una aplicación local, escuchar en 127.0.0.1. Si no, limitar por "
                    "firewall a los servidores que la necesitan.", puerto)
    if 2049 in p or 111 in p:
        agregar("bajo", "NFS / RPC expuesto",
                "Hay recursos NFS publicados que podrían montarse desde otros equipos.",
                "Revisar /etc/exports y limitar a las IP que corresponden.", 2049 if 2049 in p else 111)

    web_plana = [x for x in e.puertos if x.numero in _WEB_PLANA and not x.https]
    tiene_https = any(x.https for x in e.puertos)
    if web_plana and not tiene_https:
        importante = e.es_puerta or "Cámara" in e.tipo or e.tipo in ("MikroTik", "Impresora")
        x = web_plana[0]
        agregar("medio" if importante else "bajo", "Panel web sin cifrar",
                "La administración web no usa HTTPS: la contraseña viaja en texto plano y "
                "cualquiera en la red puede capturarla.",
                "Activar HTTPS en el equipo (aunque sea con certificado propio) y desactivar HTTP, "
                "o administrar solo desde una red separada.", x.numero,
                f"puerto {x.numero}" + (f" «{x.titulo}»" if x.titulo else ""))

    if "Cámara" in e.tipo and (37777 in p or 8000 in p or 554 in p):
        agregar("bajo", "Cámara / grabador en la red general",
                "Las cámaras y DVR suelen tener firmware viejo y vulnerabilidades conocidas.",
                "Actualizar firmware, cambiar la clave por defecto, no publicarlas con port forward "
                "y, si se puede, ponerlas en una VLAN aparte.")

    if e.upnp and e.es_puerta and es_igd(e.upnp):
        agregar("medio", "UPnP activo en el router",
                "Cualquier equipo de la red puede abrir puertos hacia Internet sin pedir permiso. "
                "Lo usan consolas y cámaras, pero también malware.",
                "Desactivar UPnP en el router y abrir a mano solo los puertos necesarios.")
    elif e.upnp and not e.es_puerta:
        agregar("info", "Anuncia UPnP",
                "El equipo se anuncia en la red por UPnP/SSDP.",
                "Normal en televisores, impresoras y NAS. Desactivar si no se usa.")
    return h


ORDEN = {"alto": 0, "medio": 1, "bajo": 2, "info": 3}


def ordenar(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    return sorted(hallazgos, key=lambda x: (ORDEN.get(x.nivel, 9), x.titulo, x.ip))
