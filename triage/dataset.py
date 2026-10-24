"""Dataset etiquetado de ejemplo: carga validada y medición de aciertos del triage."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from triage.config import ConfiguracionTriage, PrioridadYaml
from triage.evaluadores import EvaluadorPedidos
from triage.pipeline import construir_entrada, triar_pedido
from triage.schemas import Canal, OrigenResultado, Prioridad


class PedidoEjemplo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    codigo_ejemplo: Annotated[str, Field(min_length=1, max_length=20)]  # "EJ-01"
    canal: Canal
    texto: Annotated[str, Field(pattern=r"\S")]
    dependencia: str | None
    ubicacion: str | None
    prioridad_esperada: PrioridadYaml  # etiquetado manual, "P1"…"P4"
    tipo_esperado: str
    caso: str | None = None  # qué cubre el ejemplo: "regla:<id>", "ambiguo", …


class DatasetInvalido(Exception):
    def __init__(self, errores: list[str]):
        self.errores = errores
        detalle = "\n".join(f"- {e}" for e in errores)
        super().__init__(f"Dataset de ejemplo inválido:\n{detalle}")


_LISTA = TypeAdapter(list[PedidoEjemplo])


def _errores_pydantic(error: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(p) for p in detalle['loc'])}: {detalle['msg']}"
        for detalle in error.errors()
    ]


def cargar_dataset(archivo: Path, config: ConfiguracionTriage) -> list[PedidoEjemplo]:
    """Lee el dataset JSON y lo valida contra los tipos configurados."""
    try:
        ejemplos = _LISTA.validate_json(Path(archivo).read_bytes())
    except ValidationError as error:
        raise DatasetInvalido(_errores_pydantic(error)) from error

    errores: list[str] = []
    tipos = config.nombres_tipos()
    vistos: set[str] = set()
    for e in ejemplos:
        if e.tipo_esperado not in tipos:
            errores.append(f"{e.codigo_ejemplo}: el tipo «{e.tipo_esperado}» no está configurado")
        if e.codigo_ejemplo in vistos:
            errores.append(f"{e.codigo_ejemplo}: el código está repetido")
        vistos.add(e.codigo_ejemplo)
    if errores:
        raise DatasetInvalido(errores)
    return ejemplos


@dataclass(frozen=True)
class ResultadoEjemplo:
    codigo_ejemplo: str
    prioridad_esperada: Prioridad
    prioridad_obtenida: Prioridad | None  # None si quedó sin clasificar
    tipo_esperado: str
    tipo_obtenido: str | None
    origen: OrigenResultado
    duracion_ms: int

    @property
    def coincide_prioridad(self) -> bool:
        return self.prioridad_obtenida == self.prioridad_esperada

    @property
    def coincide_tipo(self) -> bool:
        return self.tipo_obtenido == self.tipo_esperado


def _porcentaje(cantidad: int, total: int) -> float:
    return round(100 * cantidad / total, 1) if total else 0.0


@dataclass(frozen=True)
class ReporteAciertos:
    resultados: list[ResultadoEjemplo]

    @property
    def aciertos_prioridad(self) -> int:
        return sum(r.coincide_prioridad for r in self.resultados)

    @property
    def aciertos_tipo(self) -> int:
        return sum(r.coincide_tipo for r in self.resultados)

    @property
    def porcentaje_prioridad(self) -> float:
        return _porcentaje(self.aciertos_prioridad, len(self.resultados))

    @property
    def porcentaje_tipo(self) -> float:
        return _porcentaje(self.aciertos_tipo, len(self.resultados))

    @property
    def duracion_promedio_ms(self) -> int:
        duraciones = [r.duracion_ms for r in self.resultados]
        return round(sum(duraciones) / len(duraciones)) if duraciones else 0

    @property
    def no_coincidentes(self) -> list[ResultadoEjemplo]:
        return [r for r in self.resultados if not (r.coincide_prioridad and r.coincide_tipo)]


def medir_aciertos(
    ejemplos: Sequence[PedidoEjemplo],
    principal: EvaluadorPedidos,
    respaldo: EvaluadorPedidos,
    config: ConfiguracionTriage,
    reloj: Callable[[], float] = time.monotonic,
) -> ReporteAciertos:
    """Ejecuta el triage de cada ejemplo, sin persistirlo, y lo compara con lo esperado."""
    resultados = []
    for e in ejemplos:
        # La misma entrada que arma el registro, así se reutiliza el caché de la demo.
        entrada = construir_entrada(
            e.texto, canal=e.canal, dependencia=e.dependencia, ubicacion=e.ubicacion
        )
        triage = triar_pedido(entrada, principal, respaldo, config, reloj=reloj)
        resultados.append(
            ResultadoEjemplo(
                codigo_ejemplo=e.codigo_ejemplo,
                prioridad_esperada=e.prioridad_esperada,
                prioridad_obtenida=triage.calculo and triage.calculo.prioridad_final,
                tipo_esperado=e.tipo_esperado,
                tipo_obtenido=triage.evaluacion and triage.evaluacion.tipo_principal,
                origen=triage.origen,
                duracion_ms=triage.duracion_ms,
            )
        )
    return ReporteAciertos(resultados)


NOMBRES_ORIGEN = {
    OrigenResultado.IA: "IA",
    OrigenResultado.RESPALDO: "Respaldo por palabras clave",
    OrigenResultado.SIN_CLASIFICACION: "Sin clasificación",
}


def _decimal(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def _clasificacion(prioridad: Prioridad | None, tipo: str | None) -> str:
    if prioridad is None:
        return "sin clasificar"
    return f"{prioridad.name} / {tipo}"


def formatear_reporte(reporte: ReporteAciertos) -> str:
    """Reporte en español para la consola (requisito 11.3)."""
    total = len(reporte.resultados)
    lineas = [
        f"Pedidos evaluados: {total}",
        f"Coincidencia de prioridad: {_decimal(reporte.porcentaje_prioridad)} % "
        f"({reporte.aciertos_prioridad} de {total})",
        f"Coincidencia de tipo principal: {_decimal(reporte.porcentaje_tipo)} % "
        f"({reporte.aciertos_tipo} de {total})",
        f"Tiempo promedio por pedido: {reporte.duracion_promedio_ms} ms",
        "",
        "Tiempo por pedido:",
        *(
            f"  {r.codigo_ejemplo:<8} {r.duracion_ms:>6} ms  {NOMBRES_ORIGEN[r.origen]}"
            for r in reporte.resultados
        ),
        "",
    ]
    if not reporte.no_coincidentes:
        lineas.append("Todos los casos coinciden con lo esperado.")
        return "\n".join(lineas)

    filas = [
        (
            r.codigo_ejemplo,
            _clasificacion(r.prioridad_esperada, r.tipo_esperado),
            _clasificacion(r.prioridad_obtenida, r.tipo_obtenido),
            NOMBRES_ORIGEN[r.origen],
        )
        for r in reporte.no_coincidentes
    ]
    encabezado = ("Código", "Esperado", "Obtenido", "Origen")
    anchos = [max(len(f[i]) for f in [encabezado, *filas]) for i in range(len(encabezado))]
    lineas.append(f"Casos no coincidentes ({len(filas)}):")
    for fila in [encabezado, *filas]:
        lineas.append(
            "  " + "  ".join(c.ljust(a) for c, a in zip(fila, anchos, strict=True)).rstrip()
        )
    return "\n".join(lineas)
