from redportes import hallazgos, informe, visitas
from redportes.clasificacion import clasificar
from redportes.modelo import Equipo, Puerto, a_dict


def eq(ip, mac="", fab="", puertos=(), ttl=64, **kw):
    e = Equipo(ip=ip, mac=mac, fabricante=fab, ttl=ttl, **kw)
    e.puertos = [Puerto(numero=p, servicio="") for p in puertos]
    return e


def test_clasificacion():
    casos = [
        (eq("1.1.1.2", fab="Zhejiang Dahua Technology", puertos=[80, 554]), "Cámara"),
        (eq("1.1.1.3", fab="Grandstream Networks", puertos=[80, 5060]), "Teléfono"),
        (eq("1.1.1.4", puertos=[9100, 80]), "Impresora"),
        (eq("1.1.1.5", puertos=[135, 445, 3389], ttl=128), "PC / servidor Windows"),
        (eq("1.1.1.6", fab="MikroTik", puertos=[8291]), "MikroTik"),
        (eq("1.1.1.7", mac="DA:00:00:00:00:01"), "Celular o notebook"),
        (eq("1.1.1.8", puertos=[8006, 22]), "Servidor Proxmox"),
    ]
    for e, esperado in casos:
        clasificar(e)
        assert e.tipo.startswith(esperado), (e.ip, e.tipo)


def test_sistema_por_banner():
    e = eq("1.1.1.9", puertos=[22])
    e.puertos[0].banner = "SSH-2.0-ROSSSH"
    clasificar(e)
    assert e.sistema == "MikroTik RouterOS" and e.tipo == "MikroTik"


def test_hallazgos():
    e = eq("1.1.1.1", puertos=[23, 80, 8728], es_puerta=True)
    e.smbv1 = True
    e.upnp = ["urn:schemas-upnp-org:device:InternetGatewayDevice:1"]
    clasificar(e)
    titulos = {h.titulo: h.nivel for h in hallazgos.evaluar(e)}
    assert titulos["Telnet abierto"] == "alto"
    assert titulos["Acepta SMBv1"] == "alto"
    assert titulos["Panel web sin cifrar"] == "medio"
    assert titulos["UPnP activo en el router"] == "medio"
    assert "API de MikroTik sin cifrar" in titulos


def test_web_con_https_no_es_hallazgo():
    e = eq("1.1.1.2", puertos=[80, 443])
    e.puertos[1].https = True
    clasificar(e)
    assert not any(h.titulo == "Panel web sin cifrar" for h in hallazgos.evaluar(e))


def _resultado(equipos, fecha="2026-11-03T10:00:00"):
    for e in equipos:
        clasificar(e)
        e.hallazgos = hallazgos.evaluar(e)
    return {
        "version": "t", "cliente": "Pyme X", "fecha": fecha, "duracion_s": 1.0,
        "red": "192.168.50.0/24",
        "interfaz": {"nombre": "eth0", "ip": "192.168.50.100", "mascara": "255.255.255.0",
                     "red": "192.168.50.0/24", "mac": "", "virtual": False},
        "puerta": "192.168.50.1", "dns": [{"ip": "192.168.50.1", "quien": "El router"}],
        "sistema": "Linux", "admin": False, "nmap": False, "puertos_revisados": [22, 23, 80, 554],
        "internet": None, "equipos": [a_dict(e) for e in equipos],
    }


def test_comparar_visitas():
    a = _resultado([eq("192.168.50.1", mac="4C:5E:0C:00:00:01", puertos=[80], es_puerta=True),
                    eq("192.168.50.20", mac="00:11:22:33:44:55", puertos=[22]),
                    eq("192.168.50.30", mac="00:11:22:33:44:66")])
    b = _resultado([eq("192.168.50.1", mac="4C:5E:0C:00:00:01", puertos=[80, 23], es_puerta=True),
                    eq("192.168.50.21", mac="00:11:22:33:44:55", puertos=[22]),
                    eq("192.168.50.40", mac="00:11:22:33:44:77")], fecha="2026-12-01T10:00:00")
    c = visitas.comparar(a, b)
    assert [e["ip"] for e in c["nuevos"]] == ["192.168.50.40"]
    assert [e["ip"] for e in c["faltan"]] == ["192.168.50.30"]
    detalles = {x["ip"]: x["detalle"] for x in c["cambios"]}
    assert "puertos nuevos: 23" in detalles["192.168.50.1"]
    assert any("cambió de IP" in d for d in detalles["192.168.50.21"])


def test_guardar_y_leer(tmp_path):
    db = tmp_path / "v.db"
    r1 = _resultado([eq("192.168.50.1", es_puerta=True)])
    r2 = _resultado([eq("192.168.50.1", es_puerta=True)], fecha="2026-12-01T10:00:00")
    i1 = visitas.guardar(r1, db)
    i2 = visitas.guardar(r2, db)
    assert visitas.anterior("Pyme X", "192.168.50.0/24", ruta=db)["fecha"] == r2["fecha"]
    assert visitas.anterior("Pyme X", "192.168.50.0/24", antes_de=i2, ruta=db)["fecha"] == r1["fecha"]
    assert visitas.obtener(i1, db)["fecha"] == r1["fecha"]
    assert len(visitas.listar("Pyme X", db)) == 2


def test_informe_html():
    r = _resultado([eq("192.168.50.1", fab="TP-Link", puertos=[80], es_puerta=True, ttl=64),
                    eq("192.168.50.60", fab="Zhejiang Dahua Technology", puertos=[80, 554]),
                    eq("192.168.50.100", es_este_equipo=True),
                    eq("192.168.50.66", fab="<script>alert(1)</script>")])
    html = informe.generar(r, None)
    assert html.startswith("<!DOCTYPE html>")
    assert "192.168.50.60" in html and "<svg" in html
    assert "Panel web sin cifrar" in html
    assert "<script>alert" not in html  # todo escapado
