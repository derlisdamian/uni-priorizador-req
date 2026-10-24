"""Orquestación de un triage completo: IA con un reintento, respaldo y motivos de revisión.

La política de fallos es acotada: IA → reintento → respaldo → sin clasificación. `triar_pedido`
nunca lanza excepciones, porque toda falla se traduce en un `ResultadoTriage`.
"""

import re
import time
from collections.abc import Callable

from triage.config import ConfiguracionTriage
from triage.evaluadores import ErrorEvaluacion, EvaluadorPedidos, TipoErrorEvaluacion
from triage.justificacion import TEXTO_SIN_CLASIFICACION, redactar_justificacion
from triage.schemas import (
    Canal,
    EntradaEvaluacion,
    EvaluacionCriterios,
    Justificacion,
    MotivoRevision,
    OrigenResultado,
    ResultadoTriage,
)
from triage.scoring import calcular_prioridad

INTENTOS_IA = 2  # el intento original y un único reintento (requisito 6.3)

_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Al menos 7 dígitos, separados a lo sumo por un espacio o guion, con prefijo + o (área) opcional.
# Así no se confunden con teléfonos los años, las aulas, las fechas ni las horas.
_TELEFONO = re.compile(r"(?<![\w+])(?:\+|\(\d{2,4}\)\s?)?\d(?:[ -]?\d){6,14}(?!\w)")


def anonimizar_texto(texto: str) -> str:
    """Reemplaza correos y teléfonos por [correo] y [telefono] (requisito 12.1)."""
    return _TELEFONO.sub("[telefono]", _CORREO.sub("[correo]", texto))


def _informado(valor: str | None) -> str | None:
    return valor.strip() or None if valor else None


def construir_entrada(
    texto: str, *, canal: Canal, dependencia: str | None, ubicacion: str | None
) -> EntradaEvaluacion:
    """Arma lo único que sale hacia el evaluador: texto anonimizado y sin datos de contacto."""
    return EntradaEvaluacion(
        texto=anonimizar_texto(texto),
        canal=canal,
        dependencia_informada=_informado(dependencia),
        ubicacion_informada=_informado(ubicacion),
    )


def _describir(rol: str, evaluador: EvaluadorPedidos, error: Exception) -> str:
    return f"{rol} ({evaluador.nombre}): {error}"


def _evaluar_con_ia(
    entrada: EntradaEvaluacion, principal: EvaluadorPedidos, errores: list[str]
) -> tuple[EvaluacionCriterios | None, int]:
    """Devuelve la evaluación (o None) y la cantidad de intentos reales contra la IA."""
    for intento in range(1, INTENTOS_IA + 1):
        try:
            return principal.evaluar(entrada), intento
        except ErrorEvaluacion as error:
            errores.append(_describir("principal", principal, error))
            if error.tipo is TipoErrorEvaluacion.NO_CONFIGURADO:
                return None, intento - 1  # sin API key no hubo llamada: no se reintenta
        except Exception as error:  # cualquier falla inesperada consume el reintento
            errores.append(_describir("principal", principal, error))
    return None, INTENTOS_IA


def _motivos(
    entrada: EntradaEvaluacion,
    evaluacion: EvaluacionCriterios | None,
    origen: OrigenResultado,
    config: ConfiguracionTriage,
) -> list[MotivoRevision]:
    # Se considera informado el dato que trajo el pedido o el que el evaluador extrajo del texto.
    dependencia = entrada.dependencia_informada or (evaluacion and evaluacion.dependencia)
    ubicacion = entrada.ubicacion_informada or (evaluacion and evaluacion.ubicacion)
    es_ia = origen is OrigenResultado.IA
    condiciones = {
        # La confianza del respaldo es siempre 0: su revisión ya la marca CLASIFICACION_RESPALDO.
        MotivoRevision.CONFIANZA_BAJA: es_ia and evaluacion.confianza < config.confianza_minima,
        MotivoRevision.TEXTO_INSUFICIENTE: evaluacion is not None and evaluacion.texto_insuficiente,
        MotivoRevision.CONFLICTO_TIPOS: evaluacion is not None and evaluacion.conflicto_tipos,
        MotivoRevision.DEPENDENCIA_NO_INFORMADA: not _informado(dependencia),
        MotivoRevision.UBICACION_NO_INFORMADA: not _informado(ubicacion),
        MotivoRevision.CLASIFICACION_RESPALDO: origen is OrigenResultado.RESPALDO,
        MotivoRevision.SIN_CLASIFICACION: origen is OrigenResultado.SIN_CLASIFICACION,
    }
    return [motivo for motivo, aplica in condiciones.items() if aplica]


def triar_pedido(
    entrada: EntradaEvaluacion,
    principal: EvaluadorPedidos,
    respaldo: EvaluadorPedidos,
    config: ConfiguracionTriage,
    reloj: Callable[[], float] = time.monotonic,
) -> ResultadoTriage:
    """Ejecuta el triage de un pedido; nunca lanza excepciones."""
    inicio = reloj()
    errores: list[str] = []
    # Defensa en profundidad: aunque el llamador ya debería haberlo hecho, es idempotente.
    entrada = entrada.model_copy(update={"texto": anonimizar_texto(entrada.texto)})

    def resultado(
        origen: OrigenResultado, evaluacion: EvaluacionCriterios | None, intentos: int
    ) -> ResultadoTriage:
        clasificado = evaluacion is not None
        calculo = (
            calcular_prioridad({c: p.puntaje for c, p in evaluacion.criterios.items()}, config)
            if clasificado
            else None
        )
        justificacion = (
            redactar_justificacion(evaluacion, calculo, origen, config)
            if clasificado
            else Justificacion(
                texto=TEXTO_SIN_CLASIFICACION, criterios_destacados=[], es_respaldo=False
            )
        )
        es_ia = origen is OrigenResultado.IA
        return ResultadoTriage(
            origen=origen,
            modelo=getattr(principal, "modelo", principal.nombre) if es_ia else None,
            evaluacion=evaluacion,
            calculo=calculo,
            justificacion=justificacion,
            motivos_revision=_motivos(entrada, evaluacion, origen, config),
            intentos_ia=intentos,
            errores=list(errores),
            version_config=config.version,
            duracion_ms=max(0, round((reloj() - inicio) * 1000)),
        )

    evaluacion_ia, intentos = _evaluar_con_ia(entrada, principal, errores)
    if evaluacion_ia is not None:
        try:
            return resultado(OrigenResultado.IA, evaluacion_ia, intentos)
        except Exception as error:
            errores.append(_describir("resultado de la IA", principal, error))

    try:
        return resultado(OrigenResultado.RESPALDO, respaldo.evaluar(entrada), intentos)
    except Exception as error:
        errores.append(_describir("respaldo", respaldo, error))

    return resultado(OrigenResultado.SIN_CLASIFICACION, None, intentos)
