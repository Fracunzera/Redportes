# Redportes

**Escáner de red local para técnicos de campo.** Llegás a un cliente, nadie sabe qué hay conectado: corrés `redportes` y en un minuto tenés el mapa de la red, qué es cada equipo, qué conviene revisar (explicado en castellano y con qué hacer) y un informe listo para guardar como PDF.

Libre, gratis y de código abierto (MIT). Funciona en **Linux, Windows y macOS**.

![Informe de ejemplo](docs/captura.png)

> Mirá un informe completo con datos inventados en [`ejemplos/informe-ejemplo.html`](ejemplos/informe-ejemplo.html) (descargalo y abrilo en el navegador).

## Qué hace

- **Mapa de la red**: de Internet al router y del router a cada equipo.
- **Qué es cada aparato**: IP, MAC, fabricante, nombre, sistema estimado, puertos abiertos y título de su panel web. Distingue routers, MikroTik, Ubiquiti, cámaras y grabadores, impresoras, teléfonos IP, servidores Windows/Linux/Proxmox, máquinas virtuales, Raspberry Pi y celulares (MAC aleatoria).
- **Qué conviene revisar**, con explicación y solución:
  Telnet, SMBv1, FTP, paneles web sin HTTPS, RDP y VNC, API de MikroTik sin cifrar, Winbox abierto, PPTP, bases de datos expuestas, NFS, cámaras en la red general y UPnP activo en el router.
- **Arreglos listos para copiar**: el comando exacto según el equipo (RouterOS en MikroTik, PowerShell en Windows, Linux), con botón *Copiar*.
- **IP WAN del router**: se la pregunta al propio router por UPnP o NAT-PMP (sin salir a Internet). Así se ve la IP privada que da el operador con **CGNAT** (100.64.x.x) o el **doble NAT**, aunque no la uses.
- **Cómo sale a Internet** (opcional, con `--internet`): saltos hasta Internet, doble NAT, CGNAT, IP pública y qué DNS usa.
- **Qué se ve desde Internet** (con `--internet`): consulta pasiva a [Shodan InternetDB](https://internetdb.shodan.io/) sobre la IP pública: puertos publicados (RDP, cámaras, Winbox…) y vulnerabilidades conocidas. No escanea nada; con CGNAT avisa que esa IP no es de tu red.
- **Diagnóstico de conexión** (pestaña *Diagnóstico* o `redportes diagnostico`): ping al router y a Internet con pérdida, latencia y jitter, prueba de cada DNS configurado contra uno público y navegación HTTPS real. Dice en castellano si el problema es la red local, el proveedor o el DNS, y se copia con un botón para pegarlo en un chat o ticket.
- **Salud de la red (0 a 100)** con semáforo y los motivos del puntaje: un número que entiende cualquiera.
- **Visitas por cliente**: guarda cada escaneo y en la siguiente visita te dice qué equipos son nuevos, cuáles ya no están y qué puertos se abrieron o cerraron.
- **Informe mensual**: evolución de la salud, equipos nuevos y desaparecidos, problemas resueltos y nuevos, pendientes y un resumen listo para pegar en una nota.
- **Inventario a Excel**: todos los equipos que pasaron por la red, con primera y última vez que se vieron.
- **Escaneo automático diario con avisos por Telegram**: te avisa si aparece un equipo desconocido, un problema grave nuevo o si baja la salud. Usa un bot tuyo: no pasa por ningún servidor de terceros.
- **Informe HTML** autocontenido (no carga nada de Internet) con botón *Guardar como PDF*.

## Qué NO hace

- No instala agentes ni modifica nada en los equipos.
- No prueba contraseñas ni explota vulnerabilidades.
- No necesita permisos de administrador (con ellos y con nmap obtiene más MACs).
- No envía nada a Internet salvo que uses `--internet` (traceroute a 8.8.8.8, IP pública con ipify y consulta a Shodan InternetDB) o `actualizar-oui`.

> ⚠️ **Usalo solo en redes donde tengas autorización.** Un escaneo de puertos puede disparar alertas en firewalls o equipos de seguridad: si hay un equipo de ciberseguridad, avisale antes.

## Instalación

### Windows (con interfaz gráfica)

Bajá el instalador `Redportes-x.y.z-instalador.exe` de la sección [Releases](https://github.com/Fracunzera/Redportes/releases/latest) y ejecutalo. No pide permisos de administrador ni necesita Python. Queda en el menú Inicio como **Redportes**.

> Como el instalador no está firmado digitalmente, Windows puede mostrar *«Windows protegió su PC»*: tocá **Más información → Ejecutar de todas formas**.

Los informes se guardan en `Documentos\Redportes`.

### Línea de comandos (Linux, Windows, macOS)

Necesitás Python 3.9 o superior.

```bash
# Recomendado: con pipx queda como comando aislado
pipx install git+https://github.com/Fracunzera/Redportes

# O con pip
pip install git+https://github.com/Fracunzera/Redportes
```

Esto instala también `redportes-gui`, la misma interfaz gráfica (en Linux necesita el paquete `python3-tk`).

**Opcional pero recomendado:** instalar [nmap](https://nmap.org/download.html) (`sudo apt install nmap`). Redportes lo usa para el descubrimiento si está; si no, todo funciona igual con Python puro (ping, TCP y tabla ARP).

**Opcional:** bajar la base completa de fabricantes de la IEEE (unos 5 MB, una sola vez):

```bash
redportes actualizar-oui
```

Sin eso usa la base de nmap si está instalado, o una lista mínima incorporada (MikroTik, Ubiquiti, Hikvision, Dahua, Raspberry Pi, virtualización…).

## Avisos por Telegram y escaneo automático

En la interfaz: **Automatizar…**

1. En Telegram, abrí **@BotFather**, mandá `/newbot` y copiá el token que te da.
2. Pegalo en Redportes, tocá **Conectar** y mandale cualquier mensaje a tu bot. Para que avise a todo un equipo, agregá el bot a un grupo y escribí en el grupo.
3. Elegí la hora y tocá **Programar**: se crea una tarea programada de Windows (o una línea de cron en Linux/macOS) que escanea todos los días y avisa solo si hay novedades.

Desde la consola:

```bash
redportes telegram --token 123456:ABC...      # conecta el bot (espera tu mensaje)
redportes programar -c "Oficina" -r 192.168.1.0/24 --hora 08:30
redportes programar --listar
redportes mensual -c "Oficina" --mes 2026-11 --abrir
redportes inventario -c "Oficina" -o inventario.csv
redportes diagnostico                          # ¿anda mal la red, el proveedor o el DNS?
```

## Redes grandes

El ping se hace sin lanzar procesos (socket ICMP en Linux/macOS, API nativa en Windows), así que una /16 lleva del orden de un minuto en Linux y unos pocos en Windows, más el tiempo de revisar puertos en los equipos que respondan. Hasta una /16 no pide confirmación; para redes más grandes hay que agregar `--forzar`. Con más de 96 equipos el mapa del informe los agrupa por /24.

La MAC y el fabricante solo se pueden obtener de los equipos del mismo segmento de red (los que ve la tabla ARP). En subredes ruteadas el tipo de equipo se estima por puertos, banners y TTL.

## Uso

```bash
# Escanea la red de la interfaz principal con 21 puertos comunes y genera el informe
redportes

# Con nombre de cliente (para el historial), todos los puertos y análisis de salida a Internet
redportes -c "Ferretería El Tornillo" -p completo --internet --abrir

# Una red puntual o puertos a elección
redportes -r 10.0.5.0/24 -p 22,80,443,8000-8100

# Ver interfaces, visitas guardadas y regenerar un informe viejo
redportes interfaces
redportes visitas -c "Ferretería El Tornillo"
redportes informe 3 --abrir
```

| Opción | Qué hace |
|---|---|
| `-r, --red` | Red a escanear (por defecto la de la interfaz principal) |
| `-i, --interfaz` | Interfaz a usar |
| `-p, --puertos` | `rapido` (21), `completo` (36), `ninguno` o lista `22,80,8000-8010` |
| `-c, --cliente` | Nombre del cliente/sitio, para comparar visitas |
| `--internet` | Analiza la salida a Internet (traceroute + IP pública) |
| `-o, --salida` | Nombre del HTML |
| `--json` | Guarda el resultado crudo en JSON |
| `--abrir` | Abre el informe al terminar |
| `--sin-nmap` | No usar nmap |
| `--no-guardar` | No guardar en el historial |
| `--forzar` | Permite redes más grandes que una /16 |

En Linux, para que nmap traiga las MAC de todos los equipos: `sudo redportes …` (sin sudo igual las saca de la tabla ARP del sistema).

El historial se guarda en `~/.local/share/redportes/visitas.db` (Linux), `%LOCALAPPDATA%\redportes` (Windows) o `~/Library/Application Support/redportes` (macOS).

## Cómo funciona

| Parte | Técnica |
|---|---|
| Descubrimiento | `nmap -sn` (si está) + barrido de ping propio + toque TCP en redes chicas + tabla ARP |
| Fabricante | Prefijo de la MAC (IEEE / nmap / lista incorporada); detecta MAC aleatorias |
| Sistema | TTL del ping, banners de SSH/FTP/Telnet y puertos característicos |
| Puertos | Conexión TCP completa, sin privilegios; lee el `<title>` de las webs |
| SMBv1 | Ofrece solo el dialecto SMBv1 y mira si el equipo lo acepta (sin autenticar) |
| UPnP | Un M-SEARCH SSDP y escucha quién responde |
| IP WAN | `GetExternalIPAddress` por UPnP IGD, o pedido NAT-PMP al puerto 5351 del router |
| Exposición | Shodan InternetDB (datos que Shodan ya tiene, actualizados semanalmente; gratis para uso no comercial) |
| Doble NAT / CGNAT | Traceroute: dos saltos privados seguidos = doble NAT; un salto en 100.64.0.0/10 = CGNAT |

## Publicar una versión

1. Subir el número en `redportes/__init__.py`.
2. En GitHub: *Releases → Draft a new release*, crear el tag `vX.Y.Z` y publicar.
3. GitHub Actions arma el instalador de Windows y lo adjunta a la release solo (tarda un par de minutos).

## Desarrollo

```bash
git clone https://github.com/Fracunzera/Redportes && cd Redportes
pip install -e ".[dev]"
pytest
python ejemplos/generar_ejemplo.py /tmp/ejemplo.html   # informe con datos de prueba
```

Las reglas de hallazgos están en [`redportes/hallazgos.py`](redportes/hallazgos.py) y la clasificación de equipos en [`redportes/clasificacion.py`](redportes/clasificacion.py): son el mejor lugar para contribuir.

## Ideas para próximas versiones

- Prueba de velocidad opcional.
- Descubrimiento por mDNS, NetBIOS, LLDP/CDP y SNMP (solo lectura).
- Varias subredes / VLANs en un mismo informe.
- Panel web opcional y autoalojado para juntar los informes de todos tus clientes.

## Licencia

[MIT](LICENSE). Usalo, modificalo y redistribuilo libremente.
