import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from redportes import velocidad as v


class _LibreSpeed(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/backend/garbage.php"):
            n = int(self.path.split("ckSize=")[1]) * 1024 * 1024
            self.send_response(200)
            self.send_header("Content-Length", str(n))
            self.end_headers()
            bloque = b"x" * 65536
            try:
                while n > 0:
                    self.wfile.write(bloque[:n])
                    n -= len(bloque)
            except OSError:
                pass
        elif self.path.startswith("/backend/empty.php"):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            while n > 0:
                n -= len(self.rfile.read(min(n, 65536)) or b"x" * n)
        except OSError:
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def _servidor():
    s = ThreadingHTTPServer(("127.0.0.1", 0), _LibreSpeed)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_medicion_contra_librespeed_local():
    s = _servidor()
    try:
        base = f"http://127.0.0.1:{s.server_address[1]}"
        srv = v.buscar_librespeed("prueba", base)
        assert srv is not None and srv.url_subida.endswith("/backend/empty.php")
        r = v.medir(srv, duracion=2.5, hilos=2)
        assert r["latencia"] is not None
        assert r["bajada"] and r["bajada"] > 10
        assert r["subida"] and r["subida"] > 10
    finally:
        s.shutdown()


def test_detener_corta_rapido():
    s = _servidor()
    try:
        srv = v.librespeed("prueba", f"http://127.0.0.1:{s.server_address[1]}", "/backend")
        import time

        t0 = time.time()
        r = v.medir(srv, duracion=30, parar=lambda: time.time() - t0 > 2)
        assert time.time() - t0 < 10
        assert r["subida"] is None
    finally:
        s.shutdown()


def test_sin_librespeed():
    s = _servidor()
    try:
        assert v.buscar_librespeed("x", f"http://127.0.0.1:{s.server_address[1]}/otra") is None
    finally:
        s.shutdown()
    assert v.buscar_librespeed("x", "http://127.0.0.1:9", timeout=1) is None


def test_leer_plan():
    assert v.leer_plan("300") == {"bajada": 300, "subida": None}
    assert v.leer_plan("300/50 Mb/s") == {"bajada": 300, "subida": 50}
    assert v.leer_plan("12,5") == {"bajada": 12.5, "subida": None}
    assert v.leer_plan("") is None
    assert v.leer_plan("nada") is None


def test_parsear_ookla():
    linea = json.dumps({"type": "result", "ping": {"latency": 9.8, "jitter": 1.2},
                        "download": {"bandwidth": 12_500_000, "latency": {"iqm": 40.1}},
                        "upload": {"bandwidth": 2_500_000, "latency": {"iqm": 80}},
                        "server": {"name": "SS Servicios", "location": "Río Gallegos"},
                        "result": {"url": "https://www.speedtest.net/result/c/abc"}})
    r = v.parsear_ookla('{"type":"log"}\n' + linea + "\n")
    assert r["bajada"] == 100.0 and r["subida"] == 20.0
    assert r["latencia_bajada"] == 40.1
    assert "SS Servicios" in r["servidor"]
    assert v.parsear_ookla("basura") == {}


def test_calificar_carga():
    assert v.calificar_carga(10, 25)[0] == "ok"
    assert v.calificar_carga(10, 80)[0] == "aviso"
    assert v.calificar_carga(10, 300)[0] == "falla"
    assert v.calificar_carga(None, 30)[0] == "omitido"


def _medida(nombre, bajada, subida, lat=10, lat_b=15, lat_s=18):
    return {"servidor": nombre, "bajada": bajada, "subida": subida, "latencia": lat, "jitter": 2,
            "latencia_bajada": lat_b, "latencia_subida": lat_s, "error": ""}


def test_concluir_proveedor_rapido_internet_lento():
    # Caso real de Río Gallegos: el plan llega completo, los servidores lejanos dan menos.
    r = v.concluir({"internet": _medida("Cloudflare", 60, 48, lat=48),
                    "proveedor": _medida("SS Servicios", 290, 293), "plan": v.leer_plan("300")})
    assert r["estado"] == "ok"
    assert "97% del plan" in r["veredicto"] and "290 Mb/s" in r["veredicto"]
    assert any("Steam" in q for q in r["que_hacer"])
    assert not any("reclamale" in q for q in r["que_hacer"])


def test_concluir_lento_de_verdad():
    r = v.concluir({"internet": _medida("Cloudflare", 80, 20), "plan": v.leer_plan("300/50")})
    assert r["estado"] == "falla" and "27% del plan" in r["veredicto"]
    assert any("reclamale" in q for q in r["que_hacer"])


def test_concluir_elige_el_mejor_y_fast():
    r = v.concluir({"internet": _medida("Cloudflare", 60, 40),
                    "fast": _medida("fast.com (Netflix · Buenos Aires, AR)", 280, 45), "plan": v.leer_plan("300")})
    assert r["estado"] == "ok" and "280 Mb/s" in r["veredicto"]
    assert any(p[0] == "Netflix vs Cloudflare" for p in r["pasos"])
    assert any(p[0].endswith("★") for p in r["pasos"])


def test_parsear_fast_y_rango():
    datos = {"targets": [{"url": "https://ipv4-c001-rgl001-ix.1.oca.nflxvideo.net/speedtest?c=ar&n=1&e=9&t=x",
                          "location": {"city": "Buenos Aires", "country": "AR"}}]}
    d = v.parsear_fast(datos)
    assert d == [{"url": datos["targets"][0]["url"], "ciudad": "Buenos Aires", "pais": "AR"}]
    assert v._rango(d[0]["url"], 1000) == ("https://ipv4-c001-rgl001-ix.1.oca.nflxvideo.net/speedtest/range/0-1000"
                                            "?c=ar&n=1&e=9&t=x")
    assert v.parsear_fast({}) == []


def test_concluir_bufferbloat_y_wifi():
    r = v.concluir({"internet": _medida("Cloudflare", 95, 20, lat_b=15, lat_s=250),
                    "plan": v.leer_plan("100"), "wifi": {"ssid": "Casa", "senal": 40, "recepcion": "144"}})
    assert r["estado"] == "falla"
    assert any("SQM" in q for q in r["que_hacer"])
    assert any("cable" in q for q in r["que_hacer"])
    assert "hecho por Fracunzera" in v.como_texto(r)


def test_concluir_todo_bien_y_sin_internet():
    r = v.concluir({"internet": _medida("Cloudflare", 300, 50), "plan": v.leer_plan("300")})
    assert r["estado"] == "ok"
    r = v.concluir({"internet": {"servidor": "Cloudflare", "bajada": None, "error": "No se pudo conectar"}})
    assert r["estado"] == "falla"
