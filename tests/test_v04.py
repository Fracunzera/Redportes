import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

import pytest

from redportes import inventario, mensual, salud, telegram, visitas
from tests.test_reglas import _resultado, eq


def test_salud():
    bien = _resultado([eq("192.168.50.1", fab="TP-Link", puertos=[443], es_puerta=True)])
    bien["equipos"][0]["puertos"][0]["https"] = True
    assert salud.calcular(bien)["puntaje"] == 100
    mal = _resultado([eq("192.168.50.1", puertos=[23, 80], es_puerta=True),
                      eq("192.168.50.2", puertos=[23, 3389], ttl=128)])
    s = salud.calcular(mal)
    assert s["puntaje"] < 60 and s["estado"] == "En riesgo" and s["motivos"]


def _guardar_dos(db):
    a = _resultado([eq("192.168.50.1", mac="4C:5E:0C:00:00:01", puertos=[80], es_puerta=True),
                    eq("192.168.50.20", mac="00:11:22:33:44:55", puertos=[23])], fecha="2026-10-20T10:00:00")
    b = _resultado([eq("192.168.50.1", mac="4C:5E:0C:00:00:01", puertos=[80], es_puerta=True),
                    eq("192.168.50.20", mac="00:11:22:33:44:55", puertos=[22]),
                    eq("192.168.50.30", mac="00:11:22:33:44:66", fab="Hikvision", puertos=[554])],
                   fecha="2026-11-15T10:00:00")
    visitas.guardar(a, db)
    visitas.guardar(b, db)
    return a, b


def test_inventario(tmp_path):
    db = tmp_path / "v.db"
    _guardar_dos(db)
    filas = inventario.armar("Pyme X", "192.168.50.0/24", db)
    assert [f["IP"] for f in filas] == ["192.168.50.1", "192.168.50.20", "192.168.50.30"]
    assert filas[2]["Primera vez"].startswith("2026-11-15") and filas[0]["Visitas en que apareció"] == 2
    destino = inventario.exportar_csv(filas, tmp_path / "inv.csv")
    texto = destino.read_bytes()
    assert texto.startswith(b"\xef\xbb\xbf") and b";" in texto.splitlines()[0]


def test_mensual(tmp_path):
    db = tmp_path / "v.db"
    _guardar_dos(db)
    d = mensual.datos("Pyme X", "192.168.50.0/24", "2026-11", db)
    assert [e["ip"] for e in d["cambios"]["nuevos"]] == ["192.168.50.30"]
    assert any(h["titulo"] == "Telnet abierto" for h in d["resueltos"])
    resumen = mensual.resumen_ejecutivo(d)
    assert "noviembre de 2026" in resumen and "Se resolvieron" in resumen
    html = mensual.generar(d)
    assert "<svg" in html and "Telnet abierto" in html
    with pytest.raises(mensual.SinVisitas):
        mensual.datos("Pyme X", "192.168.50.0/24", "2026-01", db)


def test_aviso():
    a = _resultado([eq("192.168.50.1", mac="4C:5E:0C:00:00:01", es_puerta=True)])
    b = _resultado([eq("192.168.50.1", mac="4C:5E:0C:00:00:01", es_puerta=True),
                    eq("192.168.50.9", mac="00:11:22:33:44:99", fab="<Raro>", puertos=[23])])
    texto = telegram.armar_aviso(b, visitas.comparar(a, b), a)
    assert "equipo(s) nuevo(s)" in texto and "Telnet abierto" in texto and "&lt;Raro&gt;" in texto
    assert "bajó" in texto
    assert telegram.armar_aviso(a, visitas.comparar(a, a), a) == ""


class _Telegram(BaseHTTPRequestHandler):
    enviados = []

    def _responder(self, resultado, ok=True, codigo=200):
        self.send_response(codigo)
        self.end_headers()
        self.wfile.write(json.dumps({"ok": ok, "result": resultado}).encode())

    def do_POST(self):
        metodo = self.path.rsplit("/", 1)[1]
        datos = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        if "/botMALO/" in self.path:
            return self._responder(None, False, 401)
        if metodo == "getMe":
            return self._responder({"username": "prueba_bot"})
        if metodo == "getUpdates":
            if datos.get("offset", ["0"])[0] == "0" and datos.get("timeout", ["0"])[0] == "0":
                return self._responder([{"update_id": 5, "message": {"chat": {"id": 1, "first_name": "Viejo"}}}])
            return self._responder([{"update_id": 6, "message": {"chat": {"id": -100, "title": "Soporte"}}}])
        if metodo == "sendMessage":
            _Telegram.enviados.append(datos)
            return self._responder({"message_id": 1})

    do_GET = do_POST

    def log_message(self, *a):
        pass


def test_telegram_api(monkeypatch, tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Telegram)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(telegram, "API", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(telegram, "_ruta", lambda: tmp_path / "config.json")
    try:
        assert telegram.nombre_bot("TOKEN") == "@prueba_bot"
        assert telegram.esperar_chat("TOKEN", segundos=5) == (-100, "Soporte")
        with pytest.raises(telegram.ErrorTelegram, match="token no es válido"):
            telegram.nombre_bot("MALO")
        assert not telegram.configurado()
        telegram.guardar_config({"telegram": {"token": "TOKEN", "chat_id": -100}})
        assert telegram.configurado()
        telegram.enviar("hola")
        assert _Telegram.enviados[-1]["chat_id"] == ["-100"]
    finally:
        srv.shutdown()


def test_programar_argumentos():
    from redportes import programar

    args = programar.argumentos("Ferretería X", "192.168.1.0/24", "/tmp/x", True, "rapido")
    assert args[:3] == ["escanear", "--red", "192.168.1.0/24"] and "--avisar" in args and "--internet" in args
    assert programar.nombre_tarea("Ferretería X", "192.168.1.0/24") == "Redportes - Ferretería X"
    with pytest.raises(ValueError):
        programar._validar_hora("25:00")
