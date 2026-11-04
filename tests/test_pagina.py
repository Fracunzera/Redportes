import pytest

from redportes import pagina


def _dns(pc_estado="ok", pc_ips=("185.199.108.153",), ttl_neg=None):
    pc = {"servidor": "192.168.1.1", "estado": pc_estado, "ips": list(pc_ips) if pc_estado == "ok" else [],
          "de_la_pc": True, "quien": "DNS de la PC", "ttl_negativo": ttl_neg}
    pub = {"servidor": "1.1.1.1", "estado": "ok", "ips": ["185.199.108.153"], "de_la_pc": False,
           "quien": "Cloudflare (público)"}
    return {"dominio": "sitio.com", "resultados": [pc, pub], "conclusiones": []}


@pytest.fixture
def base(monkeypatch):
    """Todo anda; cada test rompe una parte."""
    monkeypatch.setattr(pagina.diagnostico, "https", lambda: {"ok": True, "ms": 50})
    monkeypatch.setattr(pagina.consulta_dns, "comparar", lambda d: _dns())
    monkeypatch.setattr(pagina.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("185.199.108.153", 443))])
    monkeypatch.setattr("redportes.equipo_local.hosts", lambda: [])
    monkeypatch.setattr(pagina, "conectar", lambda ip, p, timeout=5: (True, 20))
    monkeypatch.setattr(pagina, "probar_https", lambda d, ip: {"etapa": "ok", "estado": 200, "ms": 120, "destino": ""})
    monkeypatch.setattr(pagina, "medir_mtu", lambda ip: {"estado": "ok", "mtu": 1500})
    return monkeypatch


def test_todo_bien(base):
    r = pagina.investigar("https://sitio.com/x")
    assert r["estado"] == "ok" and "abre bien" in r["veredicto"]
    assert [p["estado"] for p in r["pasos"]][:6] == ["ok"] * 6


def test_cache_dns_vieja(base):
    base.setattr(pagina.consulta_dns, "comparar", lambda d: _dns("no existe", ttl_neg=3600))
    r = pagina.investigar("sitio.com")
    assert "respuesta vieja" in r["veredicto"] and "60 minutos" in r["veredicto"]
    assert r["pasos"][2]["estado"] == "omitido"


def test_dns_de_la_pc_roto_no_es_falta_de_internet(base):
    base.setattr(pagina.diagnostico, "https", lambda: {"ok": False, "error": "no se pudo resolver"})
    base.setattr(pagina.consulta_dns, "comparar", lambda d: _dns("sin respuesta"))
    r = pagina.investigar("sitio.com")
    assert r["pasos"][0]["estado"] == "aviso" and "DNS de esta PC" in r["veredicto"]


def test_sin_internet(base):
    base.setattr(pagina.diagnostico, "https", lambda: {"ok": False, "error": "x"})
    base.setattr(pagina, "conectar", lambda ip, p, timeout=5: (False, "no responde"))
    assert "no anda Internet" in pagina.investigar("sitio.com")["veredicto"]


def test_hosts_bloquea(base):
    base.setattr("redportes.equipo_local.hosts", lambda: ["0.0.0.0 sitio.com"])
    assert "archivo hosts" in pagina.investigar("sitio.com")["veredicto"]


def test_puertos_cerrados(base):
    base.setattr(pagina, "conectar", lambda ip, p, timeout=5: (ip == "1.1.1.1", "no responde"))
    assert "no puede conectarse" in pagina.investigar("sitio.com")["veredicto"]


def test_certificado_vencido(base):
    base.setattr(pagina, "probar_https", lambda d, ip: {"etapa": "certificado", "error": "certificate has expired"})
    base.setattr(pagina, "emisor_certificado", lambda d, ip: "Let's Encrypt R3")
    assert "vencido" in pagina.investigar("sitio.com")["veredicto"]


def test_proxy_intercepta(base):
    base.setattr(pagina, "probar_https", lambda d, ip: {"etapa": "certificado", "error": "self-signed certificate"})
    base.setattr(pagina, "emisor_certificado", lambda d, ip: "FortiGate CA Fortinet")
    assert "intercepta" in pagina.investigar("sitio.com")["veredicto"]


def test_mtu(base):
    base.setattr(pagina, "probar_https", lambda d, ip: {"etapa": "respuesta", "error": "colgado", "colgado": True})
    base.setattr(pagina, "medir_mtu", lambda ip: {"estado": "bajo", "mtu": 1452})
    r = pagina.investigar("sitio.com")
    assert "MTU" in r["veredicto"] and "1452" in r["veredicto"]
    assert any("clamp-to-pmtu" in q for q in r["que_hacer"])


def test_error_del_servidor(base):
    base.setattr(pagina, "probar_https", lambda d, ip: {"etapa": "ok", "estado": 503, "ms": 90, "destino": ""})
    assert "error 503" in pagina.investigar("sitio.com")["veredicto"]


def test_texto(base):
    t = pagina.como_texto(pagina.investigar("sitio.com"))
    assert "¿Por qué no abre sitio.com?" in t and "✅" in t
