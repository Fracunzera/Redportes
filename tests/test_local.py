"""Prueba de punta a punta contra servicios levantados en 127.0.0.1."""

import socket
import sys

import pytest
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from redportes import puertos


class _Web(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><head><title>Panel del router</title></head></html>")

    def log_message(self, *a):
        pass


def _puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_puerto_y_titulo():
    srv = HTTPServer(("127.0.0.1", 0), _Web)
    p = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert puertos.puerto_abierto("127.0.0.1", p)
        assert not puertos.puerto_abierto("127.0.0.1", _puerto_libre())
        titulo, https = puertos.titulo_web("127.0.0.1", p, False)
        assert titulo == "Panel del router" and not https
    finally:
        srv.shutdown()


def test_banner():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    p = srv.getsockname()[1]

    def atender():
        c, _ = srv.accept()
        c.sendall(b"SSH-2.0-OpenSSH_9.2p1 Debian-2\r\n")
        c.close()

    threading.Thread(target=atender, daemon=True).start()
    assert puertos.leer_banner("127.0.0.1", p).startswith("SSH-2.0-OpenSSH_9.2p1 Debian")
    srv.close()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows tiene SMB escuchando en 445")
def test_smbv1_no_crashea_si_no_hay_servicio():
    assert puertos.acepta_smbv1("127.0.0.1", timeout=0.5) is False


def test_ping_a_localhost():
    from redportes import icmp

    r = icmp.barrido(["127.0.0.1"], timeout=1.0)
    if r is None:
        pytest.skip("este sistema no permite sockets ICMP sin privilegios")
    assert "127.0.0.1" in r
