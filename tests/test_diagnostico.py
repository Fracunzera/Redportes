import socket
import struct
import threading

from redportes import diagnostico as d


def _ping(perdida=0, prom=5.0, jitter=1.0, recibidos=10):
    p = {"ip": "x", "enviados": 10, "recibidos": recibidos, "perdida": perdida}
    if recibidos:
        p.update(min=prom - 1, prom=prom, max=prom + 3, jitter=jitter)
    return p


OK_DNS = {"servidor": "192.168.1.1", "ok": True, "ms": 12.0}
REF = {"servidor": "1.1.1.1", "ok": True, "ms": 20.0}
WEB = {"ok": True, "ms": 120}
SIS = {"ok": True, "ms": 15}


def test_todo_bien():
    pruebas, concl = d.evaluar("192.168.1.1", _ping(), {"8.8.8.8": _ping(prom=20), "1.1.1.1": _ping(prom=18)},
                               [OK_DNS], REF, SIS, WEB)
    assert all(p.estado == "ok" for p in pruebas)
    assert concl[0].startswith("Todo bien")


def test_wifi_malo():
    _, concl = d.evaluar("192.168.1.1", _ping(perdida=20, prom=60), {"8.8.8.8": _ping(perdida=20, prom=80)},
                         [OK_DNS], REF, SIS, WEB)
    assert any("red local" in c for c in concl)


def test_proveedor():
    _, concl = d.evaluar("192.168.1.1", _ping(), {"8.8.8.8": _ping(perdida=30, prom=40)},
                         [OK_DNS], REF, SIS, WEB)
    assert any("del router hacia afuera" in c for c in concl)


def test_dns_roto():
    malo = {"servidor": "192.168.1.1", "ok": False, "error": "no responde"}
    _, concl = d.evaluar("192.168.1.1", _ping(), {"8.8.8.8": _ping()}, [malo], REF,
                         {"ok": False, "error": "no se pudo resolver el nombre (DNS)"}, {"ok": False, "error": "x"})
    assert any("hay Internet pero no abren las páginas" in c for c in concl)


def test_icmp_bloqueado_pero_navega():
    _, concl = d.evaluar("192.168.1.1", _ping(), {"8.8.8.8": _ping(perdida=100, recibidos=0)},
                         [OK_DNS], REF, SIS, WEB)
    assert any("firewall que filtra ICMP" in c for c in concl)


def test_sin_internet():
    _, concl = d.evaluar("192.168.1.1", _ping(), {"8.8.8.8": _ping(perdida=100, recibidos=0)},
                         [OK_DNS], REF, SIS, {"ok": False, "error": "no respondió a tiempo"})
    assert any("No hay salida a Internet" in c for c in concl)


def test_dns_directo_local():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    puerto = srv.getsockname()[1]

    def atender():
        datos, origen = srv.recvfrom(512)
        flags, respuestas = 0x8180, 1
        srv.sendto(datos[:2] + struct.pack("!HHHHH", flags, 1, respuestas, 0, 0) + datos[12:], origen)

    threading.Thread(target=atender, daemon=True).start()
    try:
        r = d.dns_directo("127.0.0.1", puerto=puerto)
    finally:
        srv.close()
    assert r["ok"] and r["ms"] >= 0


def test_texto():
    datos = {"fecha": "2026-11-03T18:00:00", "pruebas": [{"nombre": "Ping", "estado": "ok", "resultado": "bien",
                                                         "detalle": ""}], "conclusiones": ["Todo bien."]}
    t = d.como_texto(datos)
    assert "✅ Ping: bien" in t and "• Todo bien." in t
