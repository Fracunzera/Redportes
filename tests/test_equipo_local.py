from redportes import equipo_local as e

NETSH_ES = """
Hay 1 interfaz en el sistema:

    Nombre                 : Wi-Fi
    Descripción            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 1234
    Dirección física       : 70:9c:d1:00:00:01
    Estado                 : conectado
    SSID                   : Casa
    BSSID                  : a4:2b:b0:00:00:02
    Tipo de red            : Infraestructura
    Tipo de radio          : 802.11n
    Autenticación          : WPA2-Personal
    Cifrado                : CCMP
    Modo de conexión       : Conectar automáticamente
    Canal                  : 3
    Velocidad de recepción (Mbps)  : 72.2
    Velocidad de transmisión (Mbps) : 72.2
    Señal                  : 38%
    Perfil                 : Casa
"""

NETSH_EN = """
    Name                   : Wi-Fi
    Description            : Realtek 8822CE
    State                  : connected
    SSID                   : Oficina
    BSSID                  : 00:11:22:33:44:55
    Radio type             : 802.11ac
    Authentication         : Open
    Band                   : 5 GHz
    Channel                : 44
    Receive rate (Mbps)    : 866.7
    Signal                 : 92%
"""

IPCONFIG_ES = """
Configuración IP de Windows

   Nombre de host. . . . . . . . . : DESKTOP-1
Adaptador de Ethernet Ethernet:

   Descripción . . . . . . . . . . . . . . : Realtek PCIe GbE
   DHCP habilitado . . . . . . . . . . . . : sí
   Dirección IPv4. . . . . . . . . . . . . : 192.168.3.38(Preferido)
   Servidor DHCP . . . . . . . . . . . . . : 192.168.3.1
   Servidores DNS. . . . . . . . . . . . . : 192.168.3.45

Adaptador de LAN inalámbrica Wi-Fi:

   DHCP habilitado . . . . . . . . . . . . : no
   Dirección IPv4. . . . . . . . . . . . . : 10.0.0.5(Preferido)
"""

FIREWALL_ES = """
Configuración de Perfil de dominio:
----------------------------------------------------------------------
Estado                                ACTIVAR

Configuración de Perfil privado:
----------------------------------------------------------------------
Estado                                DESACTIVAR

Configuración de Perfil público:
----------------------------------------------------------------------
Estado                                ACTIVAR
Aceptar.
"""


def test_netsh_castellano():
    w = e.parsear_netsh_wlan(NETSH_ES)
    assert w["ssid"] == "Casa" and w["senal"] == 38 and w["canal"] == 3
    assert w["banda"] == "2,4 GHz" and w["seguridad"] == "WPA2-Personal" and w["bssid"] == "a4:2b:b0:00:00:02"
    assert w["recepcion"] == "72.2" and w["estandar"] == "802.11n"


def test_netsh_ingles():
    w = e.parsear_netsh_wlan(NETSH_EN)
    assert w["ssid"] == "Oficina" and w["senal"] == 92 and w["banda"] == "5 GHz" and w["seguridad"] == "Open"


def test_netsh_desconectado():
    assert e.parsear_netsh_wlan("    Nombre : Wi-Fi\n    Estado : desconectado\n") == {}


def test_nmcli():
    t = "no:Vecino:6:130 Mbit/s:40:WPA2:AA\\:BB\\:CC\\:00\\:00\\:01:wlp2s0\n" \
        "sí:Casa:36:540 Mbit/s:81:WPA2 WPA3:AA\\:BB\\:CC\\:00\\:00\\:02:wlp2s0\n"
    w = e.parsear_nmcli_wifi(t)
    assert w["ssid"] == "Casa" and w["canal"] == 36 and w["senal"] == 81 and w["bssid"] == "AA:BB:CC:00:00:02"
    assert w["banda"] == "5 GHz" and w["interfaz"] == "wlp2s0"


def test_ipconfig_dhcp():
    assert e.parsear_ipconfig_dhcp(IPCONFIG_ES, "192.168.3.38") == {"dhcp": True, "servidor_dhcp": "192.168.3.1"}
    assert e.parsear_ipconfig_dhcp(IPCONFIG_ES, "10.0.0.5") == {"dhcp": False}


def test_ip_addr():
    t = "2: eth0    inet 192.168.1.10/24 brd 192.168.1.255 scope global dynamic noprefixroute eth0"
    assert e.parsear_ip_addr(t, "192.168.1.10") == {"dhcp": True}


def test_firewall():
    assert e.parsear_firewall_windows(FIREWALL_ES) == {"perfiles": 3, "activos": 2}


def test_hosts():
    t = "127.0.0.1 localhost\n::1 localhost ip6-localhost\n# comentario\n0.0.0.0 facebook.com  # bloqueo\n"
    assert e.entradas_hosts(t) == ["0.0.0.0 facebook.com"]


def test_observaciones():
    d = {"interfaces": [{"nombre": "Ethernet", "tipo": "Cable (Ethernet)", "ip": "192.168.3.38", "red": "192.168.3.0/24",
                         "mac": "", "virtual": False, "velocidad_mbps": 100, "duplex": "completo", "mtu": 1500,
                         "principal": True, "dhcp": False}],
         "puerta": "192.168.3.1", "wifi": e.parsear_netsh_wlan(NETSH_ES), "proxy": "", "hosts": [],
         "firewall": {"perfiles": 3, "activos": 2}, "sistema": {"disco_uso": 95, "encendido_horas": 10}}
    textos = " ".join(x["texto"] for x in e.observaciones(d))
    for esperado in ("100 Mb/s", "IP 192.168.3.38 está fija", "Señal Wi-Fi débil", "canal 3",
                     "firewall", "disco está al 95%"):
        assert esperado in textos, esperado


def test_recolectar_no_falla():
    d = e.recolectar()
    assert d["sistema"]["nombre"] and d["observaciones"]
    assert e.como_texto(d)
