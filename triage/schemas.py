"""Contratos tipados del dominio de triage, compartidos por todos sus componentes."""

from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Prioridad(IntEnum):
    """El orden natural coincide con la urgencia: P1 es la más urgente."""

    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4


class OrigenResultado(StrEnum):
    IA = "ia"
    RESPALDO = "respaldo"
    SIN_CLASIFICACION = "sin_clasificacion"


class MotivoRevision(StrEnum):
    CONFIANZA_BAJA = "confianza_baja"
    TEXTO_INSUFICIENTE = "texto_insuficiente"
    CONFLICTO_TIPOS = "conflicto_tipos"
    DEPENDENCIA_NO_INFORMADA = "dependencia_no_informada"
    UBICACION_NO_INFORMADA = "ubicacion_no_informada"
    CLASIFICACION_RESPALDO = "clasificacion_respaldo"
    SIN_CLASIFICACION = "sin_clasificacion"


class Canal(StrEnum):
    FORMULARIO = "formulario"
    TEXTO_LIBRE = "texto_libre"


Puntaje = Annotated[int, Field(strict=True, ge=0, le=3)]


class EntradaEvaluacion(BaseModel):
    """Lo único que sale hacia el evaluador (requisito 12.1): no admite datos de contacto."""

    model_config = ConfigDict(extra="forbid")

    texto: str  # ya anonimizado
    canal: Canal
    dependencia_informada: str | None
    ubicacion_informada: str | None


class PuntajeCriterio(BaseModel):
    puntaje: Puntaje
    evidencia: Annotated[list[str], Field(max_length=3)]  # fragmentos literales del texto


class EvaluacionCriterios(BaseModel):
    """Salida normalizada de cualquier evaluador."""

    descripcion_normalizada: str
    dependencia: str | None
    ubicacion: str | None
    tipo_principal: str
    tipos_secundarios: list[str]
    criterios: dict[str, PuntajeCriterio]  # claves = criterios configurados
    confianza: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    texto_insuficiente: bool
    conflicto_tipos: bool


class ReglaAplicada(BaseModel):
    id: str
    descripcion: str
    prioridad_minima: Prioridad
    produjo_cambio: bool = False  # True solo en la regla responsable del escalamiento


class CalculoPrioridad(BaseModel):
    suma_ponderada_x3: Annotated[int, Field(ge=0, le=300)]  # Σ peso × puntaje
    puntaje_total: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]
    prioridad_umbral: Prioridad
    prioridad_final: Prioridad
    reglas_aplicadas: list[ReglaAplicada]

    @model_validator(mode="after")
    def _escalamiento_solo_eleva(self) -> Self:
        if self.prioridad_final > self.prioridad_umbral:
            raise ValueError("la prioridad final no puede ser menos urgente que la del umbral")
        return self


class CriterioJustificado(BaseModel):
    clave: str
    nombre: str
    puntaje: Puntaje
    evidencia: list[str]


class Justificacion(BaseModel):
    texto: str  # párrafo en español para personas no técnicas
    criterios_destacados: list[CriterioJustificado]  # criterios con puntaje ≥ 2
    es_respaldo: bool


class ResultadoTriage(BaseModel):
    origen: OrigenResultado
    modelo: str | None  # modelo de Gemini, o None si el resultado no es de IA
    evaluacion: EvaluacionCriterios | None  # None solo si el origen es sin_clasificacion
    calculo: CalculoPrioridad | None
    justificacion: Justificacion
    motivos_revision: list[MotivoRevision]
    intentos_ia: Annotated[int, Field(ge=0, le=2)]
    errores: list[str]  # descripción técnica de cada fallo
    version_config: str
    duracion_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _invariantes_de_origen(self) -> Self:
        sin_clasificacion = self.origen is OrigenResultado.SIN_CLASIFICACION
        if sin_clasificacion != (self.evaluacion is None) or sin_clasificacion != (
            self.calculo is None
        ):
            raise ValueError(
                "evaluación y cálculo faltan si y solo si el origen es sin_clasificacion"
            )
        if (
            self.origen is OrigenResultado.RESPALDO
            and MotivoRevision.CLASIFICACION_RESPALDO not in self.motivos_revision
        ):
            raise ValueError("un resultado de respaldo requiere el motivo clasificacion_respaldo")
        return self
