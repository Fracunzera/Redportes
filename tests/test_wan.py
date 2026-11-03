import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from redportes import internet, wan

DESC = """<?xml version="1.0"?><root><device><deviceList><device><deviceList><device>
<serviceList><service>
<serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
<controlURL>/ctl/IPConn</controlURL></service></serviceList>
</device></deviceList></device></deviceList></device></root>"""

RESP = """<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
<u:GetExternalIPAddressResponse xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1">
<NewExternalIPAddress>100.64.54.77</NewExternalIPAddress></u:GetExternalIPAddressResponse>
</s:Body></s:Envelope>"""


class _Router(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(DESC.encode())

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(largo).decode()
        ok = "GetExternalIPAddress" in self.headers.get("SOAPAction", "") and "GetExternalIPAddress" in cuerpo
        self.send_response(200 if ok else 500)
        self.end_headers()
        self.wfile.write(RESP.encode() if ok else b"")

    def log_message(self, *a):
        pass


def test_servicios_wan():
    s = wan.servicios_wan(DESC, "http://192.168.1.1:5000/rootDesc.xml")
    assert s == [("urn:schemas-upnp-org:service:WANIPConnection:1", "http://192.168.1.1:5000/ctl/IPConn")]


def test_upnp_ip_externa():
    srv = HTTPServer(("127.0.0.1", 0), _Router)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/rootDesc.xml"
        r = wan.ip_wan("", [url])
        assert r["ip"] == "100.64.54.77" and r["metodo"] == "UPnP" and r["tipo"] == "cgnat"
        assert "CGNAT" in r["texto"]
    finally:
        srv.shutdown()


def test_natpmp():
    assert wan.parsear_natpmp(bytes([0, 128, 0, 0, 0, 0, 0, 1, 100, 64, 1, 2])) == "100.64.1.2"
    assert wan.parsear_natpmp(bytes([0, 128, 0, 3, 0, 0, 0, 1, 0, 0, 0, 0])) == ""


def test_sin_respuesta():
    r = wan.describir("", "")
    assert r["ip"] == "" and "no informa" in r["texto"]
    assert wan.describir("192.168.1.10", "UPnP")["tipo"] == "privada"


def test_exposicion_shodan():
    info = {"puertos": [80, 3389, 12345], "vulns": ["CVE-2019-0708"], "nombres": [], "etiquetas": []}
    hall, texto = internet.hallazgos_exposicion("203.0.113.5", info, cgnat=False)
    niveles = {h.puerto: h.nivel for h in hall if h.puerto}
    assert niveles == {80: "medio", 3389: "alto", 12345: "bajo"}
    assert any("vulnerabilidades" in h.titulo for h in hall)
    hall, texto = internet.hallazgos_exposicion("203.0.113.5", info, cgnat=True)
    assert hall == [] and "CGNAT" in texto
    hall, texto = internet.hallazgos_exposicion("203.0.113.5", {"puertos": []}, cgnat=False)
    assert hall == [] and "no registra" in texto
    json.dumps([h.__dict__ for h in hall])
