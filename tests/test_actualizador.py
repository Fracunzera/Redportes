import io
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from redportes import actualizador

CONTENIDO = {}


class _Servidor(BaseHTTPRequestHandler):
    def do_GET(self):
        datos = CONTENIDO.get(self.path)
        if datos is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, *a):
        pass


@pytest.fixture
def servidor():
    srv = HTTPServer(("127.0.0.1", 0), _Servidor)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _info(base, nombre, datos, tamano=None):
    CONTENIDO["/" + nombre] = datos
    return {"version": "9.9.9", "archivos": {nombre: {"url": f"{base}/{nombre}",
                                                     "tamano": len(datos) if tamano is None else tamano}}}


def test_forma_de_uso(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert actualizador.forma_de_uso() == "pip"
    monkeypatch.setenv("APPIMAGE", "/home/x/Redportes.AppImage")
    assert actualizador.forma_de_uso() == "appimage"


def test_pip_no_se_toca(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    with pytest.raises(RuntimeError, match="pipx install"):
        actualizador.preparar({"version": "9", "archivos": {}})


def test_appimage(monkeypatch, tmp_path, servidor):
    actual = tmp_path / "Redportes-Linux-x86_64.AppImage"
    actual.write_bytes(b"viejo")
    monkeypatch.setenv("APPIMAGE", str(actual))
    lanzados = []
    monkeypatch.setattr(actualizador, "_lanzar_desacoplado", lanzados.append)
    info = _info(servidor, "Redportes-Linux-x86_64.AppImage", b"nuevo" * 1000)
    progreso = []
    prep = actualizador.preparar(info, lambda h, t: progreso.append((h, t)))
    assert actual.read_bytes() == b"viejo"  # todavía no se reemplazó
    actualizador.aplicar(prep)
    assert actual.read_bytes() == b"nuevo" * 1000 and actual.stat().st_mode & 0o111
    assert lanzados == [[str(actual)]] and progreso[-1][0] == 5000


def test_descarga_incompleta(monkeypatch, tmp_path, servidor):
    actual = tmp_path / "R.AppImage"
    actual.write_bytes(b"viejo")
    monkeypatch.setenv("APPIMAGE", str(actual))
    info = _info(servidor, "Redportes-Linux-x86_64.AppImage", b"corto", tamano=999)
    with pytest.raises(RuntimeError, match="incompleta"):
        actualizador.preparar(info)
    assert actual.read_bytes() == b"viejo"


def test_portable(monkeypatch, tmp_path, servidor):
    import sys

    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(actualizador, "ES_WINDOWS", True)
    monkeypatch.setattr(actualizador, "es_portable", lambda: True)
    monkeypatch.setattr(actualizador, "carpeta_programa", lambda: tmp_path / "programa")
    lanzados = []
    monkeypatch.setattr(actualizador, "_lanzar_desacoplado", lanzados.append)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Redportes-9.9.9-portable/Redportes.exe", b"exe")
        z.writestr("Redportes-9.9.9-portable/portable.txt", b"x")
    prep = actualizador.preparar(_info(servidor, "Redportes-Windows-portable.zip", buf.getvalue()))
    assert prep["forma"] == "portable" and (prep["origen"] / "Redportes.exe").exists()
    actualizador.aplicar(prep)
    script = (prep["tmp"] / "actualizar.cmd").read_text()
    assert "/XD datos Informes" in script and "Redportes.exe" in script
    assert lanzados[0][0] == "cmd"


def test_cancelar(monkeypatch, tmp_path, servidor):
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "R.AppImage"))
    info = _info(servidor, "Redportes-Linux-x86_64.AppImage", b"x" * 300000)
    with pytest.raises(actualizador.Cancelado):
        actualizador.preparar(info, cancelado=lambda: True)
