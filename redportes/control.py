"""Control de un escaneo: detener en cualquier momento, límite de tiempo por etapa y avisos.

Cada etapa corre en un hilo aparte. Si el usuario detiene, se corta enseguida; si una etapa
pasa su límite, se le pide que termine con lo que tenga, se deja un aviso con una recomendación
y el escaneo sigue con lo demás. Nada puede dejar la app «trabada».
"""

from __future__ import annotations

import threading
import time


class Cancelado(Exception):
    """El usuario detuvo el escaneo."""


class Control:
    def __init__(self, progreso=lambda m: None, evento: threading.Event | None = None):
        self.progreso = progreso
        self.evento = evento or threading.Event()
        self.avisos: list[dict] = []

    def cancelado(self) -> bool:
        return self.evento.is_set()

    def detener(self) -> None:
        self.evento.set()

    def verificar(self) -> None:
        if self.cancelado():
            raise Cancelado()

    def avisar(self, texto: str, recomendacion: str = "") -> None:
        self.avisos.append({"texto": texto, "recomendacion": recomendacion})
        self.progreso("⚠ " + texto)

    def etapa(self, nombre: str, func, limite: float, al_vencer=None, aviso_cada: float = 5):
        """Corre func(parar) con un límite de tiempo.

        `parar()` devuelve True cuando hay que terminar (detenido o límite vencido); las funciones
        que lo consultan devuelven lo que llevan hecho. Devuelve el resultado (parcial si venció).
        """
        self.verificar()
        vencido = threading.Event()

        def parar() -> bool:
            return self.evento.is_set() or vencido.is_set()

        res: dict = {}

        def correr():
            try:
                res["v"] = func(parar)
            except Exception as e:  # noqa: BLE001
                res["e"] = e

        hilo = threading.Thread(target=correr, daemon=True)
        hilo.start()
        inicio = time.monotonic()
        avisos = 0
        self.progreso(f"{nombre}…")
        while hilo.is_alive():
            hilo.join(0.2)
            if self.cancelado():
                vencido.set()
                raise Cancelado()
            transcurrido = time.monotonic() - inicio
            if transcurrido >= limite:
                vencido.set()
                hilo.join(3)  # le damos un momento para que devuelva lo que tenga
                if al_vencer:
                    al_vencer(transcurrido)
                return res.get("v")
            if transcurrido // aviso_cada > avisos:
                avisos = int(transcurrido // aviso_cada)
                self.progreso(f"{nombre}… ({int(transcurrido)} s)")
        if "e" in res:
            raise res["e"]
        return res.get("v")
