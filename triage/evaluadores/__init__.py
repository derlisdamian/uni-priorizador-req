"""Puerto `EvaluadorPedidos`: único punto de acceso a la interpretación de pedidos."""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from triage.schemas import EntradaEvaluacion, EvaluacionCriterios


class TipoErrorEvaluacion(StrEnum):
    NO_CONFIGURADO = "no_configurado"  # falta la API key: no se reintenta
    TIMEOUT = "timeout"
    SERVICIO = "servicio"  # errores 4xx/5xx del servicio, incluido el 429
    RESPUESTA_INVALIDA = "respuesta_invalida"  # JSON o schema inválido, o EvaluacionInvalida
    SIN_COINCIDENCIAS = "sin_coincidencias"  # el respaldo no detectó ningún tipo


class ErrorEvaluacion(Exception):
    def __init__(self, tipo: TipoErrorEvaluacion, detalle: str):
        self.tipo = tipo
        self.detalle = detalle
        super().__init__(f"{tipo}: {detalle}")


@runtime_checkable
class EvaluadorPedidos(Protocol):
    @property
    def nombre(self) -> str: ...  # "gemini:<modelo>", "palabras_clave" o "cache+gemini:<modelo>"

    def evaluar(self, entrada: EntradaEvaluacion) -> EvaluacionCriterios: ...  # ErrorEvaluacion
