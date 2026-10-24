"""Consulta filtrada y ordenada de la bandeja (`pedidos.consultas`), contra PostgreSQL."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from pedidos.consultas import FiltrosBandeja, consultar_bandeja, opciones_filtros
from pedidos.models import EstadoPedido, Pedido
from triage.schemas import Canal, Prioridad

pytestmark = pytest.mark.django_db

AHORA = timezone.now()


def pedido(nombre: str, *, prioridad, puntaje, minutos=0, **cambios) -> Pedido:
    valores = {
        "canal": Canal.FORMULARIO,
        "texto_original": nombre,
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Bloque B",
        "prioridad_vigente": prioridad,
        "tipo_vigente": "Electricidad" if prioridad else None,
        "puntaje_total": Decimal(puntaje) if puntaje is not None else None,
        "estado": EstadoPedido.PENDIENTE,
        "recibido_en": AHORA + timedelta(minutes=minutos),
    }
    return Pedido.objects.create(**(valores | cambios))


def nombres(queryset) -> list[str]:
    return [p.texto_original for p in queryset]


def test_ordena_por_prioridad_luego_puntaje_descendente_luego_fecha_ascendente():
    pedido("p3", prioridad=3, puntaje="30.00")
    pedido("sin_clasificar", prioridad=None, puntaje=None, minutos=-10)
    pedido("p1_bajo", prioridad=1, puntaje="40.00")  # P1 por escalamiento, con puntaje menor
    pedido("p2", prioridad=2, puntaje="50.00")
    pedido("p1_alto_reciente", prioridad=1, puntaje="80.00", minutos=5)
    pedido("p1_alto_antiguo", prioridad=1, puntaje="80.00", minutos=-5)
    pedido("corregido_sin_puntaje", prioridad=2, puntaje=None, corregido=True)

    assert nombres(consultar_bandeja(FiltrosBandeja())) == [
        "p1_alto_antiguo",
        "p1_alto_reciente",
        "p1_bajo",
        "p2",
        "corregido_sin_puntaje",  # sin puntaje queda al final de su prioridad
        "p3",
        "sin_clasificar",  # sin prioridad, al final
    ]


def test_usa_la_prioridad_y_el_tipo_vigentes():
    pedido("corregido", prioridad=1, puntaje="10.00", tipo_vigente="Seguridad", corregido=True)
    pedido("original", prioridad=3, puntaje="90.00")

    assert nombres(consultar_bandeja(FiltrosBandeja())) == ["corregido", "original"]
    assert nombres(consultar_bandeja(FiltrosBandeja(tipo="Seguridad"))) == ["corregido"]


class TestFiltros:
    @pytest.fixture(autouse=True)
    def pedidos(self):
        pedido("a", prioridad=1, puntaje="90.00", tipo_vigente="Electricidad")
        pedido("b", prioridad=1, puntaje="80.00", tipo_vigente="Sanitaria")
        pedido(
            "c",
            prioridad=1,
            puntaje="70.00",
            tipo_vigente="Electricidad",
            dependencia="Rectorado",
            estado=EstadoPedido.REQUIERE_REVISION,
        )
        pedido("d", prioridad=2, puntaje="60.00", tipo_vigente="Electricidad")
        pedido(
            "e",
            prioridad=None,
            puntaje=None,
            dependencia="Rectorado",
            estado=EstadoPedido.REQUIERE_REVISION,
        )

    @pytest.mark.parametrize(
        ("filtros", "esperados"),
        [
            (FiltrosBandeja(tipo="Electricidad"), ["a", "c", "d"]),
            (FiltrosBandeja(dependencia="Rectorado"), ["c", "e"]),
            (FiltrosBandeja(dependencia="rectorado"), ["c", "e"]),  # sin distinguir mayúsculas
            (FiltrosBandeja(dependencia="Recto"), []),  # coincidencia exacta
            (FiltrosBandeja(prioridad=Prioridad.P1), ["a", "b", "c"]),
            (FiltrosBandeja(estado=EstadoPedido.REQUIERE_REVISION), ["c", "e"]),
            (FiltrosBandeja(tipo="Electricidad", prioridad=Prioridad.P1), ["a", "c"]),
            (
                FiltrosBandeja(
                    tipo="Electricidad",
                    dependencia="Rectorado",
                    prioridad=Prioridad.P1,
                    estado=EstadoPedido.REQUIERE_REVISION,
                ),
                ["c"],
            ),
            (FiltrosBandeja(tipo="Sanitaria", dependencia="Rectorado"), []),
        ],
    )
    def test_combina_los_filtros_con_y_manteniendo_el_orden(self, filtros, esperados):
        assert nombres(consultar_bandeja(filtros)) == esperados


def test_opciones_de_los_filtros(config):
    pedido("a", prioridad=1, puntaje="90.00", dependencia="Rectorado")
    pedido("b", prioridad=2, puntaje="50.00", dependencia="Facultad de Ingeniería")
    pedido("c", prioridad=3, puntaje="30.00", dependencia="Rectorado")

    opciones = opciones_filtros(config)

    assert opciones.tipos == config.nombres_tipos()
    assert opciones.dependencias == ["Facultad de Ingeniería", "Rectorado"]
    assert opciones.prioridades == [Prioridad.P1, Prioridad.P2, Prioridad.P3, Prioridad.P4]
    assert opciones.estados == [
        ("pendiente", "Pendiente"),
        ("requiere_revision", "Requiere revisión"),
        ("validado", "Validado"),
    ]
