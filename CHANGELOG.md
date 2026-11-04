# Cambios

Todas las versiones de Redportes. La más nueva, arriba.

## [0.9.0] - 2026-11-04
- **Linux con ventana:** `Redportes-Linux-x86_64.AppImage`, un solo archivo que se abre con doble clic en Debian 12, Ubuntu 22.04+, Mint o Fedora. No necesita Python. Es la misma interfaz que en Windows.
- **Herramientas → Agregar Redportes al menú de aplicaciones** (Linux).
- El AppImage también sirve por consola: `./Redportes-Linux-x86_64.AppImage escanear …`, y los escaneos programados con cron apuntan al archivo.
- En Linux los informes van a la carpeta de documentos del escritorio («Documentos» en castellano).
- Consola: `redportes gui` abre la ventana; `redportes -i` solo muestra la lista de interfaces en vez de dar error.

## [0.8.1] - 2026-11-03
- Barra de menú. **Ayuda → Buscar actualizaciones** consulta en el momento y ofrece descargar la versión nueva; **Ayuda → Avisar de versiones nuevas al abrir** prende o apaga el aviso automático cuando quieras.
- **Ayuda:** sitio web, reportar un error, qué hay de nuevo y «Acerca de» (muestra dónde se guardan los datos y los informes).
- **Herramientas:** Automatizar, inventario, carpeta de informes y actualizar la lista de fabricantes.
- Arreglo: el aviso de versión nueva podía fallar al mostrarse.

## [0.8.0] - 2026-11-03
- **¿No abre una página?** En la pestaña Diagnóstico pegás la dirección y Redportes prueba en orden: si anda Internet, el DNS (compara los de la PC con Cloudflare, Google, Quad9 y OpenDNS), el archivo hosts, la conexión al sitio, HTTPS y certificado, la respuesta del sitio y el MTU. Se frena en la primera que falla y lo explica en una frase, con qué hacer.
- Detecta caché DNS vieja (y cuánto le queda), bloqueos de AdGuard/Pi-hole, proxies que interceptan HTTPS, certificados vencidos, sitios caídos y MTU bajo (con el comando para MikroTik y Windows).
- En la consola: `redportes pagina <dirección>` y `redportes dns <dirección>`.

## [0.7.0] - 2026-11-03
- **Aviso de versión nueva:** al abrir, Redportes consulta GitHub (como mucho una vez por día, si aceptaste) y muestra un aviso con el botón para descargar.
- **Informe para compartir:** una copia del informe con las IPs, MACs y nombres tapados, para publicar capturas o pedir ayuda sin exponer la red. Botón en la ventana, o `--compartir` en la consola.
- Este registro de cambios y plantillas para reportar errores y proponer ideas.

## [0.6.2] - 2026-11-03
- Botones de descarga directa en el README y en el sitio, siempre a la última versión.
- Sitio web del proyecto.

## [0.6.1] - 2026-11-03
- **Versión portable** (`.zip`): no instala nada y guarda el historial, la configuración y los informes en su propia carpeta.

## [0.6.0] - 2026-11-03
- **Este equipo:** la configuración de la PC desde la que se escanea (IP, DHCP o fija, velocidad del enlace, Wi-Fi, proxy, firewall, archivo hosts, sistema), con avisos de lo que suele dar problemas.

## [0.5.0] - 2026-11-03
- **Diagnóstico de conexión:** ping al router y a Internet, cada DNS configurado y navegación HTTPS, con la conclusión en castellano y el botón para copiar el resultado.

## [0.4.0] - 2026-11-03
- **Salud de la red** de 0 a 100.
- **Informe mensual**, **inventario a Excel**, **avisos por Telegram** y **escaneo automático diario**.

## [0.3.0] - 2026-11-03
- IP WAN del router (CGNAT o doble NAT) por UPnP o NAT-PMP.
- Qué se ve desde Internet (Shodan InternetDB, consulta pasiva).
- Comandos listos para copiar según el equipo (MikroTik, Windows, Linux).
- Base completa de fabricantes incluida en el instalador.

## [0.2.0] - 2026-11-03
- Interfaz gráfica e instalador de Windows.
- Ping rápido para redes grandes (hasta una /16 sin confirmar).

## [0.1.0] - 2026-11-03
- Primera versión: descubrimiento de equipos, puertos, fabricante, hallazgos, salida a Internet, historial de visitas e informe HTML.
