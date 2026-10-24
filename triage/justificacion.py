"""Redacción determinística de la justificación en español (requisitos 5.1–5.5).

No usa la IA: el texto sale de plantillas con los nombres legibles de la configuración.
"""

from decimal import ROUND_HALF_UP, Decimal

from triage.config import ConfiguracionTriage
from triage.schemas import (
    CalculoPrioridad,
    CriterioJustificado,
    EvaluacionCriterios,
    Justificacion,
    OrigenResultado,
    ReglaAplicada,
)

AVISO_RESPALDO = "Clasificación de respaldo por palabras clave (sin IA); requiere revisión."
TEXTO_SIN_CLASIFICACION = (
    "No se pudo clasificar el pedido: ni la IA ni la clasificación de respaldo por palabras "
    "clave lograron interpretarlo. Requiere revisión manual para asignar la prioridad y el tipo."
)
PUNTAJE_DESTACADO = 2


def _formatear_puntaje(puntaje: Decimal) -> str:
    """Un decimal con coma, como se escribe en español: 33,3."""
    return str(puntaje.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)).replace(".", ",")


def _citar(evidencia: list[str]) -> str:
    return ", ".join(f"«{fragmento}»" for fragmento in evidencia) or "sin evidencia citada"


def _frases_prioridad(calculo: CalculoPrioridad) -> list[str]:
    final, umbral = calculo.prioridad_final.name, calculo.prioridad_umbral.name
    puntaje = f"un puntaje total de {_formatear_puntaje(calculo.puntaje_total)} sobre 100"
    responsable = next((r for r in calculo.reglas_aplicadas if r.produjo_cambio), None)
    otras = [r for r in calculo.reglas_aplicadas if r is not responsable]

    if responsable is None:
        frases = [f"Prioridad {final}, con {puntaje}, que corresponde a {umbral} por umbral."]
        frases += [_frase_regla_sin_cambio(r) for r in otras]
        if not otras:
            frases.append("No se aplicaron reglas de escalamiento.")
        return frases

    frases = [
        f"Prioridad {final}, con {puntaje}. Por umbral correspondía {umbral}, pero se elevó a "
        f"{final} por la regla «{responsable.descripcion}»."
    ]
    frases += [f"También se cumplió la regla «{r.descripcion}»." for r in otras]
    return frases


def _frase_regla_sin_cambio(regla: ReglaAplicada) -> str:
    return (
        f"Se cumplió la regla «{regla.descripcion}», "
        "pero la prioridad por umbral ya era igual o más urgente."
    )


def _frase_tipos(evaluacion: EvaluacionCriterios) -> str:
    frase = f"Tipo principal: {evaluacion.tipo_principal}"
    if evaluacion.tipos_secundarios:
        frase += f" (secundarios: {', '.join(evaluacion.tipos_secundarios)})"
    return frase + "."


def _criterios_destacados(
    evaluacion: EvaluacionCriterios, config: ConfiguracionTriage
) -> list[CriterioJustificado]:
    return [
        CriterioJustificado(
            clave=definicion.clave,
            nombre=definicion.nombre,
            puntaje=criterio.puntaje,
            evidencia=list(criterio.evidencia),
        )
        for definicion in config.criterios
        if (criterio := evaluacion.criterios.get(definicion.clave)) is not None
        and criterio.puntaje >= PUNTAJE_DESTACADO
    ]


def _frase_criterios(destacados: list[CriterioJustificado]) -> str:
    if not destacados:
        return "Ningún criterio alcanzó un puntaje medio o alto."
    detalle = "; ".join(
        f"{c.nombre} (puntaje {c.puntaje}): {_citar(c.evidencia)}" for c in destacados
    )
    return f"Criterios destacados: {detalle}."


def redactar_justificacion(
    evaluacion: EvaluacionCriterios | None,
    calculo: CalculoPrioridad | None,
    origen: OrigenResultado,
    config: ConfiguracionTriage,
) -> Justificacion:
    """Compone la justificación legible del resultado de un triage."""
    if origen is OrigenResultado.SIN_CLASIFICACION:
        return Justificacion(
            texto=TEXTO_SIN_CLASIFICACION, criterios_destacados=[], es_respaldo=False
        )
    if evaluacion is None or calculo is None:
        raise ValueError(f"un resultado de origen {origen} requiere evaluación y cálculo")

    es_respaldo = origen is OrigenResultado.RESPALDO
    destacados = _criterios_destacados(evaluacion, config)
    frases = [
        *([AVISO_RESPALDO] if es_respaldo else []),
        *_frases_prioridad(calculo),
        _frase_tipos(evaluacion),
        _frase_criterios(destacados),
    ]
    return Justificacion(
        texto=" ".join(frases), criterios_destacados=destacados, es_respaldo=es_respaldo
    )
