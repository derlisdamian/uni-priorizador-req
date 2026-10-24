"""Confirmación y corrección manual (`ServicioPedidos.confirmar` y `corregir`)."""

import pytest
from django.forms.models import model_to_dict

from pedidos.models import CorreccionManual, EstadoPedido, Pedido
from pedidos.services import DatosPedido, ErrorOperacion
from tests.pedidos.conftest import EvaluadorFalso, falla
from triage.schemas import Canal, Prioridad

pytestmark = pytest.mark.django_db


@pytest.fixture
def servicio(construir_servicio):
    return construir_servicio()


@pytest.fixture
def pedido(servicio) -> Pedido:
    return servicio.registrar(
        DatosPedido(
            canal=Canal.FORMULARIO,
            texto="Hay cables expuestos en el pasillo",
            dependencia="Facultad de Ingeniería",
            ubicacion="Pasillo del bloque B",
            contacto=None,
        )
    )


@pytest.fixture
def pedido_sin_clasificar(construir_servicio) -> tuple:
    servicio = construir_servicio(principal=EvaluadorFalso(falla(), modelo="gemini-falso"))
    pedido = servicio.registrar(
        DatosPedido(
            canal=Canal.TEXTO_LIBRE, texto="???", dependencia=None, ubicacion=None, contacto=None
        )
    )
    return servicio, pedido


def recomendacion(pedido: Pedido) -> dict:
    return model_to_dict(Pedido.objects.get(pk=pedido.pk).resultado)


class TestConfirmar:
    def test_valida_sin_cambiar_prioridad_ni_tipo(self, servicio, pedido):
        confirmado = servicio.confirmar(pedido.pk, "Marta")

        confirmado.refresh_from_db()
        assert confirmado.estado == EstadoPedido.VALIDADO
        assert confirmado.prioridad_vigente == Prioridad.P1
        assert confirmado.tipo_vigente == "Electricidad"
        assert confirmado.corregido is False
        assert confirmado.validado_por == "Marta"
        assert confirmado.validado_en is not None
        assert not confirmado.correcciones.exists()

    def test_rechaza_un_pedido_sin_clasificacion(self, pedido_sin_clasificar):
        servicio, pedido = pedido_sin_clasificar
        with pytest.raises(ErrorOperacion, match="no tiene prioridad recomendada"):
            servicio.confirmar(pedido.pk, "Marta")
        pedido.refresh_from_db()
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION

    def test_exige_responsable(self, servicio, pedido):
        with pytest.raises(ErrorOperacion, match="responsable es obligatorio"):
            servicio.confirmar(pedido.pk, "   ")

    def test_pedido_inexistente(self, servicio):
        with pytest.raises(ErrorOperacion, match="no existe"):
            servicio.confirmar(999_999, "Marta")


class TestCorregir:
    def test_registra_la_correccion_y_actualiza_los_valores_vigentes(self, servicio, pedido):
        original = recomendacion(pedido)

        correccion = servicio.corregir(
            pedido.pk,
            prioridad=Prioridad.P3,
            tipo="Infraestructura",
            motivo="  El tablero ya fue aislado  ",
            responsable=" Marta ",
        )

        correccion.refresh_from_db()
        assert correccion.creado_en is not None
        assert correccion.responsable == "Marta"
        assert correccion.motivo == "El tablero ya fue aislado"
        assert (correccion.prioridad_anterior, correccion.prioridad_nueva) == (1, 3)
        assert (correccion.tipo_anterior, correccion.tipo_nuevo) == (
            "Electricidad",
            "Infraestructura",
        )

        pedido.refresh_from_db()
        assert pedido.prioridad_vigente == Prioridad.P3
        assert pedido.tipo_vigente == "Infraestructura"
        assert pedido.corregido is True
        assert pedido.estado == EstadoPedido.VALIDADO
        assert pedido.validado_por == "Marta"
        assert recomendacion(pedido) == original  # requisito 9.4

    def test_historial_de_varias_correcciones_con_la_mas_reciente_vigente(self, servicio, pedido):
        original = recomendacion(pedido)
        primera = servicio.corregir(
            pedido.pk, prioridad=Prioridad.P2, tipo="Electricidad", motivo="Uno", responsable="A"
        )
        segunda = servicio.corregir(
            pedido.pk, prioridad=Prioridad.P2, tipo="Seguridad", motivo="Dos", responsable="B"
        )
        tercera = servicio.corregir(
            pedido.pk, prioridad=Prioridad.P4, tipo="Seguridad", motivo="Tres", responsable="C"
        )

        pedido.refresh_from_db()
        assert list(pedido.correcciones.all()) == [tercera, segunda, primera]
        assert (segunda.prioridad_anterior, segunda.tipo_anterior) == (2, "Electricidad")
        assert (tercera.prioridad_anterior, tercera.tipo_anterior) == (2, "Seguridad")
        assert pedido.prioridad_vigente == Prioridad.P4
        assert pedido.tipo_vigente == "Seguridad"
        assert pedido.puntaje_total == pedido.resultado.puntaje_total  # el puntaje no cambia
        assert recomendacion(pedido) == original

    def test_corrige_un_pedido_sin_clasificacion(self, pedido_sin_clasificar):
        servicio, pedido = pedido_sin_clasificar
        correccion = servicio.corregir(
            pedido.pk, prioridad=Prioridad.P2, tipo="TIC", motivo="Revisado", responsable="Marta"
        )
        assert (correccion.prioridad_anterior, correccion.tipo_anterior) == (None, None)
        pedido.refresh_from_db()
        assert pedido.prioridad_vigente == Prioridad.P2
        assert pedido.estado == EstadoPedido.VALIDADO

    def test_acepta_la_prioridad_como_entero(self, servicio, pedido):
        correccion = servicio.corregir(
            pedido.pk, prioridad=2, tipo="Electricidad", motivo="Ok", responsable="Marta"
        )
        assert correccion.prioridad_nueva == Prioridad.P2

    @pytest.mark.parametrize(
        ("cambios", "mensaje"),
        [
            ({"motivo": ""}, "motivo es obligatorio"),
            ({"motivo": "   "}, "motivo es obligatorio"),
            ({"responsable": ""}, "responsable es obligatorio"),
            ({"prioridad": 5}, "P1, P2, P3 o P4"),
            ({"prioridad": 0}, "P1, P2, P3 o P4"),
            ({"prioridad": "P2"}, "P1, P2, P3 o P4"),
            ({"tipo": "Jardinería"}, "no está en la lista de tipos configurados"),
            ({"prioridad": Prioridad.P1, "tipo": "Electricidad"}, "no cambia"),
        ],
    )
    def test_rechaza_correcciones_invalidas(self, servicio, pedido, cambios, mensaje):
        valores = {
            "prioridad": Prioridad.P2,
            "tipo": "Electricidad",
            "motivo": "Motivo válido",
            "responsable": "Marta",
        }
        with pytest.raises(ErrorOperacion, match=mensaje):
            servicio.corregir(pedido.pk, **(valores | cambios))
        assert not CorreccionManual.objects.exists()
        pedido.refresh_from_db()
        assert pedido.prioridad_vigente == Prioridad.P1
        assert pedido.corregido is False

    def test_pedido_inexistente(self, servicio):
        with pytest.raises(ErrorOperacion, match="no existe"):
            servicio.corregir(
                999_999, prioridad=Prioridad.P2, tipo="TIC", motivo="x", responsable="y"
            )
