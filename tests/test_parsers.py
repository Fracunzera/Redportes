from redportes import descubrimiento as d
from redportes import internet, red
from redportes.oui import fabricante, mac_aleatoria
from redportes.puertos import _paquete_smb1, lista_de_puertos


def test_ping_linux():
    s = "64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=0.512 ms"
    assert d.parsear_ping(s) == (64, 0.512)


def test_ping_windows_castellano():
    s = "Respuesta desde 192.168.1.20: bytes=32 tiempo=3ms TTL=128"
    assert d.parsear_ping(s) == (128, 3.0)


def test_ping_windows_menor_a_1ms():
    s = "Reply from 10.0.0.1: bytes=32 time<1ms TTL=255"
    assert d.parsear_ping(s) == (255, 1.0)


def test_ping_sin_respuesta():
    assert d.parsear_ping("Request timed out.") == (None, None)
    assert d.parsear_ping("Host de destino inaccesible.") == (None, None)


def test_proc_arp():
    t = ("IP address       HW type     Flags       HW address            Mask     Device\n"
         "192.168.1.1      0x1         0x2         aa:bb:cc:dd:ee:01     *        eth0\n"
         "192.168.1.9      0x1         0x0         00:00:00:00:00:00     *        eth0\n")
    assert d.parsear_proc_arp(t) == {"192.168.1.1": "AA:BB:CC:DD:EE:01"}


def test_arp_windows():
    t = ("Interfaz: 192.168.1.10 --- 0x5\n"
         "  Dirección de Internet          Dirección física      Tipo\n"
         "  192.168.1.1           4c-5e-0c-11-22-33     dinámico\n"
         "  192.168.1.255         ff-ff-ff-ff-ff-ff     estático\n"
         "  224.0.0.22            01-00-5e-00-00-16     estático\n")
    assert d.parsear_arp_a(t) == {"192.168.1.1": "4C:5E:0C:11:22:33"}


def test_arp_macos():
    t = "? (192.168.0.1) at 0:1a:2b:3c:4d:5e on en0 ifscope [ethernet]\n"
    assert d.parsear_arp_a(t) == {"192.168.0.1": "00:1A:2B:3C:4D:5E"}


def test_nmap_xml():
    xml = """<?xml version="1.0"?><nmaprun>
    <host><status state="up"/><address addr="192.168.1.1" addrtype="ipv4"/>
    <address addr="4C:5E:0C:00:00:01" addrtype="mac" vendor="Routerboard.com"/>
    <hostnames><hostname name="router.lan" type="PTR"/></hostnames></host>
    <host><status state="down"/><address addr="192.168.1.2" addrtype="ipv4"/></host>
    </nmaprun>"""
    eqs = d.parsear_nmap_xml(xml)
    assert len(eqs) == 1
    assert eqs[0].ip == "192.168.1.1" and eqs[0].fabricante == "Routerboard.com"
    assert eqs[0].nombre == "router.lan"


def test_proc_route():
    t = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
         "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\n")
    assert red.parsear_proc_route(t) == "192.168.1.1"


def test_route_print():
    t = ("Network Destination        Netmask          Gateway       Interface  Metric\n"
         "          0.0.0.0          0.0.0.0      192.168.50.1    192.168.50.60     35\n")
    assert red.parsear_route_print(t) == "192.168.50.1"


def test_dns():
    assert red.parsear_resolv_conf("# x\nnameserver 1.1.1.1\nnameserver 8.8.8.8\n") == ["1.1.1.1", "8.8.8.8"]
    t = ("   Servidores DNS. . . . . . . . . . . . . . : 192.168.1.1\n"
         "                                       8.8.8.8\n"
         "   NetBIOS sobre TCP/IP. . . . . . . . . . . : habilitado\n")
    assert red.parsear_ipconfig_dns(t) == ["192.168.1.1", "8.8.8.8"]


def test_mac():
    assert red.normalizar_mac("4c-5e-0c-aa-bb-cc") == "4C:5E:0C:AA:BB:CC"
    assert mac_aleatoria("DA:11:22:33:44:55")
    assert not mac_aleatoria("4C:5E:0C:AA:BB:CC")
    assert fabricante("4C:5E:0C:AA:BB:CC")  # MikroTik incorporado
    assert fabricante("52:54:00:12:34:56") == "QEMU/KVM"  # localmente administrada pero conocida
    assert fabricante("DA:11:22:33:44:55") == "MAC aleatoria"


def test_lista_puertos():
    assert len(lista_de_puertos("rapido")) == 21
    assert lista_de_puertos("22,80,8000-8002") == [22, 80, 8000, 8001, 8002]
    assert lista_de_puertos("ninguno") == []


def test_paquete_smb1():
    p = _paquete_smb1()
    assert int.from_bytes(p[1:4], "big") == len(p) - 4
    assert p[4:8] == b"\xffSMB" and p[8] == 0x72


def test_traceroute_linux():
    t = ("traceroute to 8.8.8.8 (8.8.8.8), 10 hops max, 60 byte packets\n"
         " 1  192.168.50.1  1.123 ms\n"
         " 2  192.168.1.1  2.004 ms\n"
         " 3  100.72.0.1  20.1 ms\n"
         " 4  *\n"
         " 5  203.0.113.1  17.5 ms\n")
    s = internet.parsear_traza(t)
    assert [x["ip"] for x in s] == ["192.168.50.1", "192.168.1.1", "100.72.0.1", "", "203.0.113.1"]
    assert s[2]["ms"] == 20.1


def test_tracert_windows():
    t = ("Traza a 8.8.8.8 sobre caminos de 10 saltos como máximo.\n\n"
         "  1    <1 ms    <1 ms    <1 ms  192.168.1.1\n"
         "  2     *        *        *     Tiempo de espera agotado para esta solicitud.\n"
         "  3     9 ms     8 ms     9 ms  181.30.1.1\n")
    s = internet.parsear_traza(t)
    assert [x["ip"] for x in s] == ["192.168.1.1", "", "181.30.1.1"]


def test_analisis_doble_nat_y_cgnat():
    saltos = [{"n": 1, "ip": "192.168.50.1", "ms": 1}, {"n": 2, "ip": "192.168.1.1", "ms": 2},
              {"n": 3, "ip": "100.72.0.1", "ms": 20}, {"n": 4, "ip": "8.8.4.4", "ms": 21}]
    a = internet.analizar_saltos(saltos, "192.168.50.1")
    assert a["doble_nat"] and a["cgnat"]
    assert any("Doble NAT" in c for c in a["conclusiones"])


def test_analisis_salida_directa():
    saltos = [{"n": 1, "ip": "192.168.0.1", "ms": 1}, {"n": 2, "ip": "190.1.2.3", "ms": 8}]
    a = internet.analizar_saltos(saltos, "192.168.0.1")
    assert not a["doble_nat"] and not a["cgnat"]
    assert "Salida directa" in a["conclusiones"][0]
