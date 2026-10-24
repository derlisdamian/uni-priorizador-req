"""Consulta de la bandeja de triage: filtros combinados con Y y orden por urgencia."""

from dataclasses import dataclass

from django.db.models import F, QuerySet

from pedidos.models import EstadoPedido, Pedido
from triage.config import ConfiguracionTriage
from triage.schemas import Prioridad

# Requisito 7.2: prioridad vigente (sin prioridad al final), puntaje descendente, fecha ascendente
ORDEN_BANDEJA = (
    F("prioridad_vigente").asc(nulls_last=True),
    F("puntaje_total").desc(nulls_last=True),
    F("recibido_en").asc(),
    F("id").asc(),
)


@dataclass(frozen=True)
class FiltrosBandeja:
    tipo: str | None = None
    dependencia: str | None = None
    prioridad: Prioridad | None = None
    estado: EstadoPedido | None = None


@dataclass(frozen=True)
class OpcionesFiltros:
    tipos: list[str]
    dependencias: list[str]
    prioridades: list[Prioridad]
    estados: list[tuple[str, str]]


def consultar_bandeja(filtros: FiltrosBandeja) -> QuerySet[Pedido]:
    """Filtra sobre los valores vigentes, de modo que una corrección se refleja en la bandeja."""
    pedidos = Pedido.objects.all()
    if filtros.tipo:
        pedidos = pedidos.filter(tipo_vigente=filtros.tipo)
    if filtros.dependencia:
        pedidos = pedidos.filter(dependencia__iexact=filtros.dependencia)
    if filtros.prioridad is not None:
        pedidos = pedidos.filter(prioridad_vigente=filtros.prioridad)
    if filtros.estado:
        pedidos = pedidos.filter(estado=filtros.estado)
    return pedidos.order_by(*ORDEN_BANDEJA)


def opciones_filtros(config: ConfiguracionTriage) -> OpcionesFiltros:
    """Tipos de la configuración, dependencias registradas, prioridades y estados."""
    dependencias = (
        Pedido.objects.order_by("dependencia").values_list("dependencia", flat=True).distinct()
    )
    return OpcionesFiltros(
        tipos=config.nombres_tipos(),
        dependencias=list(dependencias),
        prioridades=list(Prioridad),
        estados=list(EstadoPedido.choices),
    )
