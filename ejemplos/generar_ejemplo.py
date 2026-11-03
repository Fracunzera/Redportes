"""Genera un informe de ejemplo con datos inventados: python ejemplos/generar_ejemplo.py salida.html"""
from redportes import informe, hallazgos, visitas
from redportes.clasificacion import clasificar
from redportes.modelo import Equipo, Puerto, a_dict
from redportes.internet import analizar_saltos

def eq(ip, mac, fab, puertos=(), ttl=64, nombre="", **kw):
    e = Equipo(ip=ip, mac=mac, fabricante=fab, ttl=ttl, nombre=nombre, latencia_ms=3.0, **kw)
    e.puertos = [Puerto(numero=p, servicio=s, titulo=t) for p, s, t in puertos]
    return e

eqs = [
 eq("192.168.50.1","50:C7:BF:00:00:01","TP-Link",[(80,"HTTP","TL-WR840N")],es_puerta=True),
 eq("192.168.50.10","00:0B:82:00:00:10","Grandstream Networks",[(80,"HTTP","Grandstream GXP1610"),(5060,"SIP","")]),
 eq("192.168.50.11","00:0B:82:00:00:11","Grandstream Networks",[(80,"HTTP",""),(5060,"SIP","")]),
 eq("192.168.50.20","70:85:C2:00:00:20","ASRock",[(135,"MS-RPC",""),(445,"SMB",""),(3389,"Escritorio remoto (RDP)","")],ttl=128,nombre="CAJA-PC",smbv1=True),
 eq("192.168.50.21","00:0B:4F:00:00:21","Verifone",[]),
 eq("192.168.50.30","00:1E:0B:00:00:30","HP",[(9100,"Impresión directa",""),(80,"HTTP","HP LaserJet M404")],ttl=255),
 eq("192.168.50.60","3C:EF:8C:00:53:3C","Zhejiang Dahua Technology",[(80,"HTTP","WEB SERVICE"),(554,"RTSP",""),(37777,"Dahua","")]),
 eq("192.168.50.61","3C:EF:8C:00:53:3D","Zhejiang Dahua Technology",[(80,"HTTP","WEB SERVICE"),(554,"RTSP","")]),
 eq("192.168.50.40","4C:5E:0C:00:00:40","MikroTik",[(8291,"Winbox",""),(23,"Telnet",""),(8728,"API MikroTik","")]),
 eq("192.168.50.50","DA:A1:19:00:00:50","MAC aleatoria",[]),
 eq("192.168.50.51","64:A2:F9:00:00:51","Xiaomi",[]),
 eq("192.168.50.100","D8:3A:DD:00:01:00","Raspberry Pi",[(22,"SSH","")],nombre="portatil-tecnico",es_este_equipo=True),
]
for e in eqs:
    clasificar(e); e.hallazgos = hallazgos.evaluar(e)
saltos=[{"n":1,"ip":"192.168.50.1","ms":1.0},{"n":2,"ip":"192.168.1.1","ms":2.0},{"n":3,"ip":"100.72.0.1","ms":20.0},{"n":4,"ip":"","ms":None},{"n":5,"ip":"200.51.100.1","ms":23.0}]
inet = analizar_saltos(saltos,"192.168.50.1"); inet["ip_publica"]="200.51.100.77"
r = {"version":"0.1.0","cliente":"Ferretería El Tornillo","fecha":"2026-11-03T16:20:00","duracion_s":38.2,"red":"192.168.50.0/24",
 "interfaz":{"nombre":"wlan0","ip":"192.168.50.100","mascara":"255.255.255.0","red":"192.168.50.0/24","mac":"","virtual":False},
 "puerta":"192.168.50.1","dns":[{"ip":"192.168.50.1","quien":"El router"}],"sistema":"Linux","admin":False,"nmap":True,
 "puertos_revisados":[21,22,23,80,135,445,554,3389,5060,8291,8728,9100,37777],"internet":inet,"equipos":[a_dict(e) for e in eqs]}
prev = {**r, "fecha":"2026-09-10T11:00:00", "equipos":[x for x in r["equipos"] if x["ip"] not in ("192.168.50.61","192.168.50.40")]}
import sys
open(sys.argv[1],"w").write(informe.generar(r, visitas.comparar(prev, r)))
