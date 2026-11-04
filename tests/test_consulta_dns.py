import socket
import struct
import threading

from redportes import consulta_dns as c


def _nombre(n):
    return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\x00"


def _respuesta(ident, rcode=0, respuestas=(), autoridad=()):
    cab = struct.pack("!HHHHHH", ident, 0x8180 | rcode, 1, len(respuestas), len(autoridad), 0)
    q = _nombre("redportes.blucaro.site") + struct.pack("!HH", 1, 1)
    cuerpo = b""
    for tipo, ttl, rdata in list(respuestas) + list(autoridad):
        cuerpo += b"\xc0\x0c" + struct.pack("!HHIH", tipo, 1, ttl, len(rdata)) + rdata
    return cab + q + cuerpo


def test_limpiar():
    assert c.limpiar("https://Redportes.blucaro.site/algo?x=1") == "redportes.blucaro.site"
    assert c.limpiar("  www.ejemplo.com.ar:8080/  ") == "www.ejemplo.com.ar"
    assert c.limpiar("http://user:clave@sitio.com") == "sitio.com"


def test_parsear_cname_y_a():
    cname = _nombre("fracunzera.github.io")
    datos = _respuesta(1, 0, [(5, 3600, cname), (1, 300, socket.inet_aton("185.199.108.153"))])
    r = c.parsear_respuesta(datos)
    assert r["cname"] == "fracunzera.github.io" and r["ips"] == ["185.199.108.153"] and r["ttl"] == 300


def test_parsear_nxdomain_con_soa():
    soa = _nombre("ns1.hostinger.com") + _nombre("dns.hostinger.com") + struct.pack("!IIIII", 1, 2, 3, 4, 3600)
    r = c.parsear_respuesta(_respuesta(1, 3, [], [(6, 14400, soa)]))
    assert r["rcode"] == 3 and r["ttl_negativo"] == 3600


def _res(servidor, estado, ips=(), pc=True, **kw):
    return {"servidor": servidor, "estado": estado, "ips": list(ips), "de_la_pc": pc, "ms": 20.0, **kw}


def test_conclusion_cache_vieja():
    res = [_res("192.168.1.1", "no existe", ttl_negativo=3600),
           _res("1.1.1.1", "ok", ["185.199.108.153"], pc=False)]
    concl = " ".join(c.conclusiones("redportes.blucaro.site", res))
    assert "respuesta vieja" in concl and "1 hora" in concl or "60 minutos" in concl


def test_conclusion_bloqueado_y_todo_bien():
    res = [_res("192.168.3.45", "bloqueado", ["0.0.0.0"]), _res("8.8.8.8", "ok", ["1.2.3.4"], pc=False)]
    assert "bloquea" in c.conclusiones("x.com", res)[0]
    res = [_res("192.168.1.1", "ok", ["1.2.3.4"]), _res("8.8.8.8", "ok", ["1.2.3.4"], pc=False)]
    assert c.conclusiones("x.com", res)[0].startswith("Todos los DNS")


def test_no_existe_en_ningun_lado():
    res = [_res("192.168.1.1", "no existe"), _res("8.8.8.8", "no existe", pc=False)]
    assert "no existe para ningún DNS público" in c.conclusiones("noexiste.xyz", res)[0]


def test_consultar_servidor_local():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    puerto = srv.getsockname()[1]

    def atender():
        datos, origen = srv.recvfrom(512)
        ident = struct.unpack("!H", datos[:2])[0]
        srv.sendto(_respuesta(ident, 0, [(1, 60, socket.inet_aton("0.0.0.0"))]), origen)

    threading.Thread(target=atender, daemon=True).start()
    try:
        r = c.consultar("127.0.0.1", "redportes.blucaro.site", puerto=puerto)
    finally:
        srv.close()
    assert r["estado"] == "bloqueado"
