"""Avisos por Telegram con un bot propio de cada usuario (sin servidores intermedios).

1. El usuario crea un bot con @BotFather y copia el token.
2. Le manda cualquier mensaje al bot (o lo agrega a un grupo y escribe ahí).
3. Redportes lee ese mensaje con getUpdates y guarda el chat_id solo.
"""

from __future__ import annotations

import html
import json
import time
import urllib.error
import urllib.parse
import urllib.request


API = "https://api.telegram.org"


class ErrorTelegram(RuntimeError):
    pass


# ---------------------------------------------------------------- configuración

def _ruta():
    from redportes import config

    return config.ruta()


def leer_config() -> dict:
    try:
        return json.loads(_ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guardar_config(cfg: dict) -> None:
    _ruta().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def configurado() -> bool:
    t = leer_config().get("telegram") or {}
    return bool(t.get("token") and t.get("chat_id"))


# ---------------------------------------------------------------- API

def _llamar(token: str, metodo: str, datos: dict | None = None, timeout: float = 15) -> object:
    url = f"{API}/bot{token.strip()}/{metodo}"
    cuerpo = urllib.parse.urlencode(datos).encode() if datos else None
    req = urllib.request.Request(url, data=cuerpo, headers={"User-Agent": "redportes"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read().decode()).get("description", "")
        except Exception:  # noqa: BLE001
            desc = ""
        if e.code == 401 or e.code == 404:
            raise ErrorTelegram("El token no es válido. Copialo de nuevo desde @BotFather.") from None
        raise ErrorTelegram(f"Telegram respondió {e.code}: {desc}") from None
    except OSError as e:
        raise ErrorTelegram(f"No se pudo conectar con Telegram: {e}") from None
    if not res.get("ok"):
        raise ErrorTelegram(res.get("description", "Error de Telegram"))
    return res["result"]


def nombre_bot(token: str) -> str:
    return "@" + _llamar(token, "getMe")["username"]


def esperar_chat(token: str, segundos: float = 120, cancelado=lambda: False) -> tuple[int, str]:
    """Espera a que alguien le escriba al bot y devuelve (chat_id, nombre del chat)."""
    # Descarta mensajes viejos para quedarse con el primero que llegue a partir de ahora.
    viejos = _llamar(token, "getUpdates", {"timeout": 0})
    offset = (viejos[-1]["update_id"] + 1) if viejos else 0
    fin = time.monotonic() + segundos
    while time.monotonic() < fin and not cancelado():
        for u in _llamar(token, "getUpdates", {"timeout": 10, "offset": offset}, timeout=20):
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
            chat = msg.get("chat")
            if chat:
                nombre = chat.get("title") or " ".join(
                    x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username", "")
                return chat["id"], nombre
    raise ErrorTelegram("No llegó ningún mensaje al bot. Escribile algo y probá de nuevo.")


def enviar(texto: str, token: str | None = None, chat_id: int | str | None = None) -> None:
    if token is None or chat_id is None:
        t = leer_config().get("telegram") or {}
        token, chat_id = t.get("token"), t.get("chat_id")
    if not token or not chat_id:
        raise ErrorTelegram("Los avisos por Telegram no están configurados.")
    _llamar(token, "sendMessage", {"chat_id": chat_id, "text": texto[:4000], "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"})


# ---------------------------------------------------------------- mensajes

def _lista(items: list[str], maximo: int = 10) -> str:
    extra = f"\n… y {len(items) - maximo} más" if len(items) > maximo else ""
    return "\n".join(items[:maximo]) + extra


def armar_aviso(r: dict, cambios: dict | None, previo: dict | None) -> str:
    """Texto del aviso, o "" si no hay nada que avisar."""
    from redportes.salud import calcular

    e = html.escape
    partes = []
    if cambios and cambios["nuevos"]:
        partes.append(f"🆕 <b>{len(cambios['nuevos'])} equipo(s) nuevo(s):</b>\n" + _lista([
            f"• <code>{e(x['ip'])}</code> {e(x.get('tipo', ''))} — {e(x.get('fabricante') or 'sin fabricante')}"
            + (f" <code>{e(x['mac'])}</code>" if x.get("mac") else "") for x in cambios["nuevos"]]))

    def altos(res):
        hs = [(h["titulo"], h["ip"], h.get("puerto")) for eq in res["equipos"] for h in eq.get("hallazgos", [])
              if h["nivel"] == "alto"]
        hs += [(h["titulo"], h["ip"], h.get("puerto")) for h in ((res.get("internet") or {}).get("hallazgos") or [])
               if h["nivel"] == "alto"]
        return hs

    nuevos_altos = [h for h in altos(r) if not previo or h not in altos(previo)]
    if nuevos_altos:
        partes.append("🔴 <b>Problemas graves nuevos:</b>\n" + _lista(
            [f"• {e(t)} — <code>{e(ip)}</code>" + (f" (puerto {p})" if p else "") for t, ip, p in nuevos_altos]))

    if previo:
        antes = (previo.get("salud") or calcular(previo))["puntaje"]
        ahora = (r.get("salud") or calcular(r))["puntaje"]
        if ahora < antes:
            partes.append(f"📉 <b>La salud bajó:</b> {antes} → {ahora}/100")

    if not partes:
        return ""
    cab = f"🛰 <b>Redportes</b> · {e(r.get('cliente') or 'Red')} ({e(r['red'])})"
    return cab + "\n\n" + "\n\n".join(partes) + "\n\n<i>Redportes · hecho por Fracunzera</i>"
