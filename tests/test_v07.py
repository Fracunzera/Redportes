import json

from redportes import actualizaciones, compartir, informe
from tests.test_reglas import _resultado, eq


def test_tapar_ip():
    assert compartir.tapar_ip("192.168.3.45") == "x.x.x.45"
    assert compartir.tapar_ip("100.64.54.12") == "100.64.x.x"
    assert compartir.tapar_ip("170.233.31.217") == "x.x.x.x"
    assert compartir.tapar_ip("8.8.8.8") == "8.8.8.8"
    assert compartir.tapar_ip("255.255.255.0") == "255.255.255.0"


def test_anonimizar():
    r = _resultado([eq("192.168.50.1", mac="4C:5E:0C:12:34:56", fab="MikroTik", puertos=[23], es_puerta=True,
                       nombre="router-ferreteria")])
    r["cliente"] = "Ferretería López"
    r["internet"] = {"ip_publica": "170.233.31.217", "conclusiones": ["sale por 170.233.31.217"], "saltos": []}
    a = compartir.anonimizar(r)
    texto = json.dumps(a, ensure_ascii=False)
    for secreto in ("192.168.50.1", "12:34:56", "router-ferreteria", "Ferretería López", "170.233.31.217"):
        assert secreto not in texto, secreto
    assert "4C:5E:0C:xx:xx:xx" in texto and "x.x.x.1" in texto
    assert a["equipos"][0]["fabricante"] == "MikroTik"
    html = informe.generar_compartible(r)
    assert "Versión para compartir" in html and "Ferretería López" not in html and "192.168.50.1" not in html


def test_versiones():
    assert actualizaciones.es_mas_nueva("0.10.0", "0.9.3")
    assert not actualizaciones.es_mas_nueva("0.7.0", "0.7.0")
    assert actualizaciones.es_mas_nueva("v1.0", "0.9.9")


def test_hay_nueva(monkeypatch):
    llamadas = []

    def falso():
        llamadas.append(1)
        return {"version": "99.0.0", "url": "u", "notas": ""}

    monkeypatch.setattr(actualizaciones, "consultar", falso)
    cfg = {}
    assert actualizaciones.hay_nueva(cfg)["version"] == "99.0.0"
    assert actualizaciones.hay_nueva(cfg)["version"] == "99.0.0"  # segunda vez: no consulta de nuevo
    assert len(llamadas) == 1
