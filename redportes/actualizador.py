"""Actualización desde la propia app: baja la versión nueva y la instala según cómo se usa Redportes.

- AppImage (Linux): reemplaza el archivo y se reinicia.
- Instalador de Windows: corre el instalador nuevo en modo silencioso y se reinicia.
- Portable de Windows: reemplaza los archivos del programa (no toca datos\\ ni Informes\\) y se reinicia.
- Instalado con pip: no se toca solo; se indica el comando.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from redportes.sistema import ES_WINDOWS, carpeta_programa, entorno_sistema, es_portable

ARCHIVOS = {
    "appimage": "Redportes-Linux-x86_64.AppImage",
    "instalador": "Redportes-Windows-instalador.exe",
    "portable": "Redportes-Windows-portable.zip",
}
COMANDO_PIP = "pipx install --force git+https://github.com/Fracunzera/Redportes"


class Cancelado(Exception):
    pass


def forma_de_uso() -> str:
    """'appimage', 'instalador', 'portable' o 'pip'."""
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if getattr(sys, "frozen", False) and ES_WINDOWS:
        return "portable" if es_portable() else "instalador"
    return "pip"


def archivo_para(info: dict, forma: str | None = None) -> dict | None:
    """{'url', 'tamano', 'nombre'} del archivo de la release que corresponde a esta instalación."""
    nombre = ARCHIVOS.get(forma or forma_de_uso())
    if not nombre:
        return None
    a = (info.get("archivos") or {}).get(nombre)
    return {**a, "nombre": nombre} if a else None


def descargar(url: str, destino: Path, tamano: int, progreso=lambda hecho, total: None,
              cancelado=lambda: False) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "redportes"})
    hecho = 0
    with urllib.request.urlopen(req, timeout=30) as r, destino.open("wb") as f:
        total = int(r.headers.get("Content-Length") or tamano or 0)
        while True:
            if cancelado():
                raise Cancelado()
            bloque = r.read(65536)
            if not bloque:
                break
            f.write(bloque)
            hecho += len(bloque)
            progreso(hecho, total)
    if tamano and destino.stat().st_size != tamano:
        destino.unlink(missing_ok=True)
        raise RuntimeError(f"La descarga quedó incompleta ({hecho} de {tamano} bytes). Probá de nuevo.")
    return destino


def _lanzar_desacoplado(cmd: list[str]) -> None:
    if ES_WINDOWS:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) \
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(cmd, creationflags=flags, close_fds=True)
    else:
        env = entorno_sistema() or dict(os.environ)
        for var in ("APPIMAGE", "APPDIR", "ARGV0", "OWD"):
            env.pop(var, None)
        subprocess.Popen(cmd, env=env, start_new_session=True, close_fds=True)


def preparar(info: dict, progreso=lambda hecho, total: None, cancelado=lambda: False) -> dict:
    """Baja (y deja listo) lo necesario. No cierra ni reinicia nada todavía."""
    forma = forma_de_uso()
    if forma == "pip":
        raise RuntimeError(f"Redportes está instalado con pip. Para actualizarlo corré:\n\n{COMANDO_PIP}")
    archivo = archivo_para(info, forma)
    if not archivo:
        raise RuntimeError("La versión nueva todavía no tiene el archivo para este sistema. Probá en unos minutos.")

    if forma == "appimage":
        actual = Path(os.environ["APPIMAGE"])
        nuevo = actual.with_name(actual.name + ".nuevo")
        try:
            descargar(archivo["url"], nuevo, archivo["tamano"], progreso, cancelado)
        except PermissionError:
            raise RuntimeError(f"No hay permiso para escribir en {actual.parent}. Bajalo a mano desde la página "
                               "de descargas o mové el AppImage a una carpeta tuya.") from None
        nuevo.chmod(0o755)
        return {"forma": forma, "nuevo": nuevo, "actual": actual}

    tmp = Path(tempfile.mkdtemp(prefix="redportes_act_"))
    destino = tmp / archivo["nombre"]
    descargar(archivo["url"], destino, archivo["tamano"], progreso, cancelado)
    if forma == "instalador":
        return {"forma": forma, "instalador": destino}

    with zipfile.ZipFile(destino) as z:
        z.extractall(tmp / "nuevo")
    carpetas = [d for d in (tmp / "nuevo").iterdir() if d.is_dir()]
    origen = carpetas[0] if len(carpetas) == 1 else tmp / "nuevo"
    if not (origen / "Redportes.exe").exists():
        raise RuntimeError("El zip descargado no tiene Redportes.exe.")
    return {"forma": forma, "origen": origen, "tmp": tmp}


def mensaje(prep: dict) -> str:
    return {
        "appimage": "Listo. Redportes se va a cerrar y abrir de nuevo con la versión nueva.",
        "instalador": "Listo. Redportes se va a cerrar, se instala la versión nueva (verás una barra de "
                      "progreso) y se vuelve a abrir solo.",
        "portable": "Listo. Redportes se va a cerrar, se reemplazan los archivos del programa (tus datos e "
                    "informes quedan) y se vuelve a abrir solo.",
    }[prep["forma"]]


def aplicar(prep: dict) -> None:
    """Instala lo preparado y lanza la versión nueva. Quien llama debe cerrar la app enseguida."""
    forma = prep["forma"]
    if forma == "appimage":
        os.replace(prep["nuevo"], prep["actual"])  # el que está corriendo sigue funcionando hasta cerrarse
        _lanzar_desacoplado([str(prep["actual"])])
    elif forma == "instalador":
        # /SILENT: solo muestra el progreso; al terminar el instalador vuelve a abrir Redportes.
        _lanzar_desacoplado([str(prep["instalador"]), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    else:
        programa = carpeta_programa()
        tmp = prep["tmp"]
        script = tmp / "actualizar.cmd"
        script.write_text(
            "@echo off\r\n"
            ":espera\r\n"
            f'tasklist /fi "PID eq {os.getpid()}" | find "{os.getpid()}" >nul && '
            f'(timeout /t 1 /nobreak >nul & goto espera)\r\n'
            f'robocopy "{prep["origen"]}" "{programa}" /E /XD datos Informes /XF portable.txt '
            f'/R:5 /W:1 /NFL /NDL /NJH /NJS /NP >nul\r\n'
            f'start "" "{programa / "Redportes.exe"}"\r\n'
            f'rd /s /q "{tmp}"\r\n', encoding="utf-8")
        _lanzar_desacoplado(["cmd", "/c", str(script)])


def limpiar_restos() -> None:
    """Borra un AppImage «.nuevo» que haya quedado de una actualización interrumpida."""
    if os.environ.get("APPIMAGE"):
        resto = Path(os.environ["APPIMAGE"] + ".nuevo")
        if resto.exists():
            try:
                resto.unlink()
            except OSError:
                pass

