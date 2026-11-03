"""Estructuras de datos del escaneo."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

NIVELES = ("alto", "medio", "bajo", "info")


@dataclass
class Puerto:
    numero: int
    servicio: str
    titulo: str = ""   # <title> de la web, si es HTTP
    banner: str = ""   # primera línea que manda el servicio (SSH, FTP, Telnet)
    https: bool = False
    a_https: bool = False  # HTTP que redirige a HTTPS


@dataclass
class Hallazgo:
    nivel: str          # alto | medio | bajo | info
    titulo: str
    que_es: str
    que_hacer: str
    ip: str = ""
    puerto: int | None = None
    detalle: str = ""  # dato puntual del equipo (puerto, título de la web…)
    comando: str = ""  # arreglo listo para copiar (según la marca/sistema)


@dataclass
class Equipo:
    ip: str
    mac: str = ""
    fabricante: str = ""
    nombre: str = ""
    ttl: int | None = None
    latencia_ms: float | None = None
    descubierto_por: list[str] = field(default_factory=list)
    puertos: list[Puerto] = field(default_factory=list)
    tipo: str = ""
    sistema: str = ""
    upnp: list[str] = field(default_factory=list)
    smbv1: bool = False
    es_puerta: bool = False
    es_este_equipo: bool = False
    hallazgos: list[Hallazgo] = field(default_factory=list)

    def marcar(self, metodo: str) -> None:
        if metodo not in self.descubierto_por:
            self.descubierto_por.append(metodo)

    def abiertos(self) -> set[int]:
        return {p.numero for p in self.puertos}

    @property
    def clave(self) -> str:
        """Identificador estable entre visitas: la MAC si existe y no es aleatoria."""
        from redportes.oui import mac_aleatoria

        if self.mac and not mac_aleatoria(self.mac):
            return self.mac
        return self.ip


def equipo_desde_dict(d: dict) -> Equipo:
    d = dict(d)
    d["puertos"] = [Puerto(**p) for p in d.get("puertos", [])]
    d["hallazgos"] = [Hallazgo(**h) for h in d.get("hallazgos", [])]
    return Equipo(**d)


def a_dict(obj) -> dict:
    return asdict(obj)
