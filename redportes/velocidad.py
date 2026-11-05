"""Prueba de velocidad: hacia Internet (Cloudflare), hasta el proveedor (LibreSpeed) y Ookla opcional.

Además de bajada y subida mide la latencia *mientras* se baja y se sube, que es lo que explica
el clásico «cuando alguien descarga algo se cortan las videollamadas» (bufferbloat).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import ssl
import statistics
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from redportes import __autor__, __version__
from redportes.sistema import contexto_ssl, ejecutar_detallado

CLOUDFLARE = "https://speed.cloudflare.com"
AGENTE = f"Mozilla/5.0 (redportes {__version__})"
DURACION = 8.0          # segundos por sentido
CALENTAMIENTO = 1.5     # lo primero no cuenta: TCP todavía está acelerando
HILOS = 4
TOPE_BYTES = 2_000_000_000   # por sentido, por si la conexión es enorme
_BLOQUE = 64 * 1024
_RELLENO = os.urandom(1024 * 1024)


class _Corte(Exception):
    """Se terminó el tiempo (o el usuario detuvo la prueba) en medio de una transferencia."""


# ---------------------------------------------------------------- servidores

class Servidor:
    """Dónde se baja, se sube y se mide la latencia."""

    def __init__(self, nombre: str, url_bajada, url_subida: str, host: str, puerto: int,
                 verificar: bool = True):
        self.nombre = nombre
        self.url_bajada = url_bajada      # función(bytes) -> url
        self.url_subida = url_subida
        self.host = host
        self.puerto = puerto
        self.verificar = verificar
        self.por_http = False

    def contexto(self):
        if self.verificar:
            return contexto_ssl()
        ctx = ssl.create_default_context()    # speedtests internos del proveedor: certificado propio
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


def cloudflare() -> Servidor:
    return Servidor("Cloudflare", lambda n: f"{CLOUDFLARE}/__down?bytes={n}", f"{CLOUDFLARE}/__up",
                    "speed.cloudflare.com", 443)


def _host_puerto(url: str) -> tuple[str, int]:
    p = urlsplit(url)
    return p.hostname or "", p.port or (443 if p.scheme == "https" else 80)


def librespeed(nombre: str, base: str, ruta: str) -> Servidor:
    raiz = base.rstrip("/") + ruta
    host, puerto = _host_puerto(base)
    return Servidor(nombre, lambda n: f"{raiz}/garbage.php?ckSize={max(1, min(100, n // 1_000_000))}",
                    f"{raiz}/empty.php", host, puerto, verificar=False)


def _abrir(srv: Servidor, url: str, data=None, timeout: float = 8, cabeceras: dict | None = None):
    h = {"User-Agent": AGENTE, "Cache-Control": "no-cache"}
    h.update(cabeceras or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
    return urllib.request.urlopen(req, timeout=timeout, context=srv.contexto())


def buscar_librespeed(nombre: str, base: str, timeout: float = 4) -> Servidor | None:
    """Prueba dónde están garbage.php / empty.php en un speedtest LibreSpeed."""
    for ruta in ("/backend", ""):
        srv = librespeed(nombre, base, ruta)
        try:
            with _abrir(srv, srv.url_subida, timeout=timeout) as r:
                r.read(1000)
            with _abrir(srv, srv.url_bajada(1_000_000), timeout=timeout) as r:
                if len(r.read(200_000)) < 100_000:
                    continue
            return srv
        except urllib.error.HTTPError:
            continue
        except Exception:  # noqa: BLE001 — el servidor no responde: no tiene sentido otra ruta
            return None
    return None


# ---------------------------------------------------------------- latencia

def latencia_tcp(host: str, puerto: int, timeout: float = 3) -> float | None:
    """Tiempo de apertura de una conexión TCP: un ida y vuelta, sin depender de ICMP."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, puerto), timeout=timeout):
            return (time.perf_counter() - t0) * 1000
    except OSError:
        return None


def jitter(muestras: list[float]) -> float | None:
    if len(muestras) < 2:
        return None
    return statistics.mean(abs(a - b) for a, b in zip(muestras, muestras[1:]))


def latencia_http(srv: "Servidor", timeout: float = 3) -> float | None:
    """Plan B cuando no hay salida TCP directa (proxy de por medio): tiempo de un pedido vacío."""
    t0 = time.perf_counter()
    try:
        with _abrir(srv, srv.url_bajada(0) if srv.nombre == "Cloudflare" else srv.url_subida,
                    timeout=timeout) as r:
            r.read(100)
        return (time.perf_counter() - t0) * 1000
    except Exception:  # noqa: BLE001
        return None


def _latencia(srv: "Servidor", timeout: float = 3) -> float | None:
    if srv.por_http:
        return latencia_http(srv, timeout)
    return latencia_tcp(srv.host, srv.puerto, timeout)


def medir_latencia(srv: "Servidor", veces: int = 10, parar=None) -> list[float]:
    if latencia_tcp(srv.host, srv.puerto) is None and latencia_http(srv) is not None:
        srv.por_http = True     # hay un proxy: la latencia incluye al proxy, pero sirve para comparar
    res = []
    for _ in range(veces):
        if parar and parar():
            break
        ms = _latencia(srv)
        if ms is not None:
            res.append(ms)
        time.sleep(0.15)
    return res


class _Sondeo(threading.Thread):
    """Mide la latencia cada medio segundo mientras dura una transferencia."""

    def __init__(self, srv: "Servidor", desde: float):
        super().__init__(daemon=True)
        self.srv, self.desde = srv, desde
        self.muestras: list[float] = []
        self.fin = threading.Event()

    def run(self):
        while not self.fin.wait(0.5):
            if time.perf_counter() < self.desde:
                continue
            ms = _latencia(self.srv, timeout=2)
            self.muestras.append(ms if ms is not None else 2000.0)


# ---------------------------------------------------------------- transferencia

class _Contador:
    def __init__(self):
        self.lock = threading.Lock()
        self.total = 0
        self.errores: list[str] = []

    def sumar(self, n: int):
        with self.lock:
            self.total += n


def _velocidad(transferir, srv: Servidor, duracion: float, hilos: int, parar, progreso, que: str) -> dict:
    """Corre `transferir(srv, contador, hasta, parar)` en varios hilos y calcula Mb/s sin el calentamiento."""
    cont = _Contador()
    inicio = time.perf_counter()
    hasta = inicio + duracion
    sondeo = _Sondeo(srv, inicio + CALENTAMIENTO)
    sondeo.start()

    def hilo():
        while time.perf_counter() < hasta and cont.total < TOPE_BYTES and not (parar and parar()):
            try:
                transferir(srv, cont, hasta, parar)
            except _Corte:
                return
            except Exception as e:  # noqa: BLE001
                cont.errores.append(str(e)[:120])
                if len(cont.errores) > hilos * 3:
                    return
                time.sleep(0.3)

    ts = [threading.Thread(target=hilo, daemon=True) for _ in range(hilos)]
    for t in ts:
        t.start()
    marca, en_marca = None, 0
    ultimo_aviso = 0.0
    while any(t.is_alive() for t in ts):
        ahora = time.perf_counter()
        if marca is None and ahora >= inicio + CALENTAMIENTO:
            marca, en_marca = ahora, cont.total
        if progreso and ahora - ultimo_aviso >= 2 and marca:
            ultimo_aviso = ahora
            parcial = (cont.total - en_marca) * 8 / max(ahora - marca, 0.01) / 1e6
            progreso(f"{que}: {parcial:.0f} Mb/s…")
        if ahora > hasta + 3:      # algún hilo colgado: no esperarlo
            break
        time.sleep(0.1)
    fin = min(time.perf_counter(), hasta)
    sondeo.fin.set()
    if marca is None or fin - marca < 1 or cont.total - en_marca <= 0:
        mbps = None if not cont.total else cont.total * 8 / max(fin - inicio, 0.01) / 1e6
    else:
        mbps = (cont.total - en_marca) * 8 / (fin - marca) / 1e6
    return {"mbps": round(mbps, 1) if mbps else None, "bytes": cont.total,
            "latencia": sondeo.muestras, "error": cont.errores[0] if cont.errores and not cont.total else ""}


def _bajar(srv: Servidor, cont: _Contador, hasta: float, parar):
    with _abrir(srv, srv.url_bajada(25_000_000)) as r:
        while True:
            if time.perf_counter() >= hasta or (parar and parar()):
                raise _Corte
            bloque = r.read(_BLOQUE)
            if not bloque:
                return
            cont.sumar(len(bloque))


def _subir(srv: Servidor, cont: _Contador, hasta: float, parar, tam: int = 8 * 1024 * 1024):
    def cuerpo():
        enviados = 0
        while enviados < tam:
            if time.perf_counter() >= hasta or (parar and parar()):
                raise _Corte
            pedazo = _RELLENO[: min(_BLOQUE * 4, tam - enviados)]
            enviados += len(pedazo)
            cont.sumar(len(pedazo))
            yield pedazo

    try:
        with _abrir(srv, srv.url_subida, data=cuerpo(), timeout=10,
                    cabeceras={"Content-Type": "application/octet-stream", "Content-Length": str(tam)}) as r:
            r.read(1000)
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), _Corte):
            raise _Corte from None
        raise


def medir(srv: Servidor, duracion: float = DURACION, hilos: int = HILOS, parar=None, progreso=None) -> dict:
    """Latencia en reposo, bajada y subida (cada una con su latencia con carga) contra un servidor."""
    aviso = progreso or (lambda _m: None)
    aviso(f"Latencia hasta {srv.nombre}…")
    reposo = medir_latencia(srv, parar=parar)
    res = {"servidor": srv.nombre, "latencia": round(statistics.median(reposo), 1) if reposo else None,
           "jitter": round(jitter(reposo), 1) if jitter(reposo) is not None else None,
           "bajada": None, "subida": None, "latencia_bajada": None, "latencia_subida": None, "error": ""}
    if not reposo:
        res["error"] = f"No se pudo conectar con {srv.host}"
        return res
    if srv.por_http:
        res["proxy"] = True
    for sentido, func in (("bajada", _bajar), ("subida", _subir)):
        if parar and parar():
            break
        aviso(f"{'Bajada' if sentido == 'bajada' else 'Subida'} desde {srv.nombre}…")
        m = _velocidad(func, srv, duracion, hilos, parar, aviso,
                       f"{'Bajada' if sentido == 'bajada' else 'Subida'} ({srv.nombre})")
        res[sentido] = m["mbps"]
        if m["latencia"]:
            res[f"latencia_{sentido}"] = round(statistics.median(m["latencia"]), 1)
        if m["error"] and not res["error"]:
            res["error"] = m["error"]
    return res


# ---------------------------------------------------------------- Ookla (opcional)

def ookla_disponible() -> str:
    """Ruta del `speedtest` oficial de Ookla, si está instalado (no el speedtest-cli de Python)."""
    ruta = shutil.which("speedtest")
    if not ruta:
        return ""
    salida, estado = ejecutar_detallado([ruta, "--version"], timeout=10)
    return ruta if estado == "ok" and "ookla" in salida.lower() else ""


def parsear_ookla(texto: str) -> dict:
    for linea in reversed(texto.strip().splitlines()):
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if d.get("type") != "result":
            continue
        srv = d.get("server") or {}
        return {
            "servidor": f"Ookla · {srv.get('name', '')} ({srv.get('location', '')})".replace(" ()", ""),
            "bajada": round(d["download"]["bandwidth"] * 8 / 1e6, 1),
            "subida": round(d["upload"]["bandwidth"] * 8 / 1e6, 1),
            "latencia": round(d["ping"]["latency"], 1), "jitter": round(d["ping"].get("jitter", 0), 1),
            "latencia_bajada": round((d["download"].get("latency") or {}).get("iqm", 0), 1) or None,
            "latencia_subida": round((d["upload"].get("latency") or {}).get("iqm", 0), 1) or None,
            "error": "", "enlace": (d.get("result") or {}).get("url", ""),
        }
    return {}


def ookla(ruta: str, parar=None) -> dict:
    salida, estado = ejecutar_detallado([ruta, "--accept-license", "--accept-gdpr", "-f", "jsonl"],
                                        timeout=120, cancelado=parar)
    r = parsear_ookla(salida) if estado == "ok" else {}
    return r or {"servidor": "Ookla", "error": "La prueba de Ookla no devolvió resultado"
                 + (" (tardó demasiado)" if estado == "tiempo" else "")}


# ---------------------------------------------------------------- plan y conclusiones

def leer_plan(texto) -> dict | None:
    """«300», «300/50» o «300 / 50 Mb/s» → {"bajada": 300, "subida": 50}."""
    import re

    if not texto:
        return None
    nums = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", str(texto))]
    if not nums or nums[0] <= 0:
        return None
    return {"bajada": nums[0], "subida": nums[1] if len(nums) > 1 and nums[1] > 0 else None}


def _mbps(v) -> str:
    if v is None:
        return "—"
    return f"{v:.0f} Mb/s" if v >= 10 else f"{v:.1f} Mb/s"


def calificar_carga(reposo, con_carga) -> tuple[str, str]:
    """(estado, texto) según cuánto sube la latencia con la conexión cargada."""
    if reposo is None or con_carga is None:
        return "omitido", "sin datos"
    extra = con_carga - reposo
    texto = f"{con_carga:.0f} ms (+{max(extra, 0):.0f} ms)"
    if extra < 30:
        return "ok", texto + " · bien"
    if extra < 100:
        return "aviso", texto + " · se nota en videollamadas y juegos"
    return "falla", texto + " · las videollamadas se cortan cuando alguien descarga"


def concluir(r: dict) -> dict:
    """Agrega estado, veredicto, qué hacer y la lista de pasos al resultado."""
    inet, prov, ook, plan, w = r.get("internet") or {}, r.get("proveedor"), r.get("ookla"), r.get("plan"), r.get("wifi") or {}
    pasos, hacer = [], []
    estado = "ok"

    def peor(e):
        nonlocal estado
        orden = {"ok": 0, "aviso": 1, "falla": 2}
        if orden.get(e, 0) > orden[estado]:
            estado = e

    principal = inet if inet.get("bajada") else (ook if ook and ook.get("bajada") else None)
    for m in (inet, prov, ook):
        if not m:
            continue
        nombre = m["servidor"] if m is not inet else "Internet (Cloudflare)"
        prefijo = ""
        if m is prov:
            nombre, prefijo = "Hasta tu proveedor", f"{m['servidor']}: "
        if m.get("bajada") is None and m.get("error"):
            pasos.append((nombre, "falla", m["error"]))
            continue
        pasos.append((nombre, "info", f"{prefijo}bajada {_mbps(m.get('bajada'))} · subida {_mbps(m.get('subida'))} · "
                                      f"latencia {m.get('latencia') or '—'} ms · jitter {m.get('jitter') or '—'} ms"))

    if not principal:
        r.update(estado="falla", veredicto="No se pudo medir la velocidad.",
                 que_hacer=["Probá «Probar mi conexión»: puede que no haya Internet o que un proxy/firewall "
                            "bloquee speed.cloudflare.com."], pasos=pasos)
        return r

    bajada, subida = principal["bajada"], principal.get("subida")
    if principal.get("proxy"):
        pasos.append(("Salida por proxy", "info", "la red sale por un proxy: la latencia medida incluye al proxy"))
    veredicto = f"Bajada {_mbps(bajada)} · subida {_mbps(subida)} · latencia {principal.get('latencia') or '—'} ms"

    # Plan contratado
    if plan:
        pct = bajada / plan["bajada"] * 100
        e = "ok" if pct >= 80 else "aviso" if pct >= 50 else "falla"
        detalle = f"bajada al {pct:.0f}% de {plan['bajada']:g} Mb/s"
        if plan.get("subida") and subida:
            detalle += f" · subida al {subida / plan['subida'] * 100:.0f}% de {plan['subida']:g} Mb/s"
        pasos.append(("Plan contratado", e, detalle))
        veredicto += f" ({pct:.0f}% del plan)"
        peor(e)

    # Proveedor vs Internet
    if prov and prov.get("bajada") and inet.get("bajada"):
        if prov["bajada"] > inet["bajada"] * 1.5:
            pasos.append(("¿Dónde está el límite?", "aviso",
                          f"hasta el proveedor llega {_mbps(prov['bajada'])} pero hacia Internet {_mbps(inet['bajada'])}"))
            hacer.append("Tu conexión hasta el proveedor anda bien: el límite está más allá (la salida a Internet del "
                         "proveedor o el camino a ese servidor). Si pasa seguido, es para reclamarle al proveedor "
                         "con estos números.")
            peor("aviso")
        else:
            pasos.append(("¿Dónde está el límite?", "info",
                          "hasta el proveedor y hacia Internet da parecido: el límite es tu conexión "
                          "(o la red/Wi-Fi de este lado)"))

    # Latencia con carga (bufferbloat)
    peor_carga = ("omitido", "sin datos")
    for sentido in ("bajada", "subida"):
        e, texto = calificar_carga(principal.get("latencia"), principal.get(f"latencia_{sentido}"))
        pasos.append((f"Latencia mientras {'baja' if sentido == 'bajada' else 'sube'}", e, texto))
        if {"falla": 2, "aviso": 1}.get(e, 0) > {"falla": 2, "aviso": 1}.get(peor_carga[0], 0):
            peor_carga = (e, texto)
    if peor_carga[0] in ("aviso", "falla"):
        peor(peor_carga[0])
        hacer.append("Con la conexión cargada la latencia se dispara (bufferbloat): por eso se cortan las "
                     "videollamadas cuando alguien descarga o sube algo. Se arregla en el router con SQM / QoS "
                     "(cake o fq_codel) limitado al ~90% de la velocidad medida; en MikroTik, una cola simple tipo cake.")

    if principal.get("jitter") and principal["jitter"] > 20:
        peor("aviso")
        hacer.append(f"La latencia varía mucho ({principal['jitter']:.0f} ms de jitter): afecta llamadas y juegos. "
                     "Suele ser Wi-Fi saturado o un enlace con problemas.")

    # Wi-Fi
    if w:
        senal = w.get("senal")
        enlace = w.get("recepcion") or w.get("transmision") or ""
        detalle = f"«{w.get('ssid', '')}» señal {senal if senal is not None else '—'}%"
        if enlace:
            detalle += f", enlace {enlace} Mb/s"
        if w.get("banda"):
            detalle += f", {w['banda']}"
        flojo = isinstance(senal, int) and senal < 60
        pasos.append(("Estás por Wi-Fi", "aviso" if flojo else "info", detalle))
        lento = plan and bajada < plan["bajada"] * 0.8
        if flojo or lento:
            hacer.append("Estás midiendo por Wi-Fi" + (" con señal floja" if flojo else "") +
                         ": antes de culpar al proveedor, repetí la prueba con cable o al lado del router. "
                         "Si con cable da bien, el problema es el Wi-Fi, no la conexión.")

    if plan and bajada < plan["bajada"] * 0.5 and not w:
        hacer.append("Llega menos de la mitad del plan por cable: probá en otro horario y, si se repite, "
                     "reclamale al proveedor con el resultado (botón «Copiar resultado»).")

    r.update(estado=estado, veredicto=veredicto, que_hacer=hacer or ["La conexión rinde bien."], pasos=pasos)
    return r


# ---------------------------------------------------------------- todo junto

def _detectar_proveedor(parar=None) -> list[dict]:
    """Proveedores conocidos en el camino (traceroute corto + DNS inverso)."""
    from redportes import internet

    cmd = internet.comando_traza(saltos=8, rapido=True)
    saltos = []
    if cmd:
        salida, _ = ejecutar_detallado(cmd, timeout=30, cancelado=parar)
        saltos = internet.analizar_saltos(internet.parsear_traza(salida), "").get("saltos", [])
    return internet.proveedores_del_camino(saltos, internet.ip_publica())


def ejecutar(plan=None, usar_ookla: bool = False, url_proveedor: str = "", progreso=None, parar=None,
             duracion: float = DURACION) -> dict:
    from redportes import equipo_local

    aviso = progreso or (lambda _m: None)
    r = {"version": __version__, "autor": __autor__, "fecha": time.strftime("%Y-%m-%d %H:%M"),
         "plan": leer_plan(plan), "internet": {}, "proveedor": None, "ookla": None, "wifi": {}}
    try:
        r["wifi"] = equipo_local.wifi()
    except Exception:  # noqa: BLE001
        r["wifi"] = {}

    r["internet"] = medir(cloudflare(), duracion=duracion, parar=parar, progreso=aviso)

    if not (parar and parar()):
        aviso("Buscando el speedtest de tu proveedor…")
        bases = [(p["nombre"], b) for p in _detectar_proveedor(parar) for b in p["bases"]]
        if url_proveedor:
            bases.append(("tu proveedor", url_proveedor))
        for nombre, base in bases:
            if parar and parar():
                break
            srv = buscar_librespeed(nombre, base)
            if srv:
                r["proveedor"] = medir(srv, duracion=max(duracion * 0.75, 3), parar=parar, progreso=aviso)
                break

    if usar_ookla and not (parar and parar()):
        ruta = ookla_disponible()
        if ruta:
            aviso("Prueba de Ookla (tarda unos 30 segundos)…")
            r["ookla"] = ookla(ruta, parar)
    r["cancelado"] = bool(parar and parar())
    return concluir(r)


def como_texto(r: dict) -> str:
    marca = {"ok": "✔", "aviso": "⚠", "falla": "✖", "omitido": "·", "info": "ℹ"}
    lineas = [f"Prueba de velocidad · {r.get('fecha', '')}", "", r["veredicto"], ""]
    for nombre, est, detalle in r["pasos"]:
        lineas.append(f"{marca.get(est, '')} {nombre}: {detalle}")
    if r.get("que_hacer"):
        lineas += ["", "Qué hacer:"] + [f"• {q}" for q in r["que_hacer"]]
    if r.get("ookla") and r["ookla"].get("enlace"):
        lineas.append(f"Resultado de Ookla: {r['ookla']['enlace']}")
    lineas += ["", f"Redportes {r.get('version', __version__)} · hecho por {__autor__}"]
    return "\n".join(lineas)
