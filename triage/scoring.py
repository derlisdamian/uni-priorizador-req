"""Motor de reglas: puntaje total, prioridad por umbral y escalamiento.

Funciones puras y determinísticas (requisito 4.8): sin I/O y con aritmética entera
para que los bordes de los umbrales sean exactos.
"""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from triage.config import Condicion, ConfiguracionTriage
from triage.schemas import CalculoPrioridad, Prioridad, ReglaAplicada

_DOS_DECIMALES = Decimal("0.01")


def _validar_puntajes(puntajes: Mapping[str, int], config: ConfiguracionTriage) -> None:
    claves = config.claves_criterios()
    errores = [f"falta el criterio «{c}»" for c in claves if c not in puntajes]
    errores += [f"criterio desconocido «{c}»" for c in puntajes if c not in claves]
    errores += [
        f"el puntaje de «{c}» debe ser un entero entre 0 y 3 ({v!r})"
        for c, v in puntajes.items()
        if c in claves and (type(v) is not int or not 0 <= v <= 3)
    ]
    if errores:
        raise ValueError("Puntajes inválidos: " + "; ".join(errores))


def _cumple(condicion: Condicion, puntajes: Mapping[str, int]) -> bool:
    valor = puntajes[condicion.criterio]
    if condicion.operador == "igual":
        return valor == condicion.valor
    return valor >= condicion.valor


def calcular_prioridad(
    puntajes: Mapping[str, int], config: ConfiguracionTriage
) -> CalculoPrioridad:
    """Calcula el puntaje total y la prioridad P1–P4.

    Lanza `ValueError` si faltan criterios, hay claves desconocidas o valores fuera de 0–3.
    """
    _validar_puntajes(puntajes, config)

    # Σ peso × puntaje (0–300): el puntaje total es esta suma / 3. Los informativos pesan 0.
    suma_x3 = sum(c.peso * puntajes[c.clave] for c in config.criterios)
    prioridad_umbral = next(
        (u.prioridad for u in config.umbrales if suma_x3 >= 3 * u.minimo), Prioridad.P4
    )

    cumplidas = [r for r in config.reglas if all(_cumple(cond, puntajes) for cond in r.condiciones)]
    # Una regla solo eleva: se toma la más urgente entre el umbral y las reglas cumplidas.
    prioridad_final = Prioridad(min([prioridad_umbral, *(r.prioridad_minima for r in cumplidas)]))
    responsable = (
        next(r for r in cumplidas if r.prioridad_minima == prioridad_final)
        if prioridad_final < prioridad_umbral
        else None
    )

    return CalculoPrioridad(
        suma_ponderada_x3=suma_x3,
        puntaje_total=(Decimal(suma_x3) / 3).quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP),
        prioridad_umbral=prioridad_umbral,
        prioridad_final=prioridad_final,
        reglas_aplicadas=[
            ReglaAplicada(
                id=r.id,
                descripcion=r.descripcion,
                prioridad_minima=r.prioridad_minima,
                produjo_cambio=r is responsable,
            )
            for r in cumplidas
        ],
    )
