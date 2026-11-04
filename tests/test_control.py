import sys
import threading
import time

import pytest

from redportes import descubrimiento, puertos
from redportes.control import Cancelado, Control
from redportes.sistema import ejecutar_detallado


def test_etapa_normal():
    c = Control()
    assert c.etapa("x", lambda parar: 42, 5) == 42


def test_etapa_vence_y_devuelve_parcial():
    c = Control()

    def lenta(parar):
        hecho = []
        while not parar():
            hecho.append(1)
            time.sleep(0.05)
        return "parcial"

    avisos = []
    inicio = time.monotonic()
    r = c.etapa("lenta", lenta, 0.5, al_vencer=lambda t: avisos.append(t))
    assert r == "parcial" and avisos and time.monotonic() - inicio < 3


def test_detener():
    c = Control()
    threading.Timer(0.3, c.detener).start()
    with pytest.raises(Cancelado):
        c.etapa("eterna", lambda parar: time.sleep(30), 60)


def test_ejecutar_con_tiempo_y_cancelar():
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    inicio = time.monotonic()
    assert ejecutar_detallado(cmd, timeout=0.5)[1] == "tiempo"
    assert ejecutar_detallado(cmd, timeout=30, cancelado=lambda: time.monotonic() - inicio > 1.5)[1] == "cancelado"
    assert time.monotonic() - inicio < 6
    salida, estado = ejecutar_detallado([sys.executable, "-c", "print('hola')"])
    assert estado == "ok" and salida.strip() == "hola"


def test_ejecutar_no_espera_entrada():
    # Un programa que lee de la entrada no debe quedar colgado (antes pasaba con nmap en Windows).
    salida, estado = ejecutar_detallado([sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"], timeout=5)
    assert estado == "ok" and salida.strip() == "0"


def test_nmap_que_no_responde(monkeypatch):
    monkeypatch.setattr(descubrimiento, "tiene", lambda p: p == "nmap")
    monkeypatch.setattr(descubrimiento, "descubrir_con_nmap", lambda red, limite, parar: ([], "tiempo"))
    monkeypatch.setattr("redportes.icmp.barrido", lambda *a, **k: {})
    monkeypatch.setattr(descubrimiento, "tabla_arp", lambda: {})
    monkeypatch.setattr(descubrimiento, "toque_tcp", lambda ip: False)
    avisos = []
    descubrimiento.descubrir("192.0.2.0/29", True, avisar=lambda t, r="": avisos.append((t, r)))
    assert avisos and "nmap" in avisos[0][0] and "Npcap" in avisos[0][1]


def test_equipos_con_firewall(monkeypatch):
    monkeypatch.setattr(puertos, "estado_puerto",
                        lambda ip, p, timeout=0.8: "filtrado" if ip == "10.0.0.9" else "cerrado")
    avisos = []
    puertos.escanear(["10.0.0.5", "10.0.0.9"], puertos.RAPIDO, avisar=lambda t, r="": avisos.append(t))
    assert any("10.0.0.9" in a and "firewall" in a for a in avisos)
    assert not any("10.0.0.5" in a for a in avisos)
