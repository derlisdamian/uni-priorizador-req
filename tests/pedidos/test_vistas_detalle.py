"""Detalle del pedido con su confirmación y su corrección manual."""

import pytest
from django.urls import reverse

from pedidos.models import CorreccionManual, EstadoPedido, Pedido
from pedidos.services import DatosPedido
from tests.pedidos.conftest import EvaluadorFalso, evaluacion, falla
from triage.schemas import Canal, Prioridad

pytestmark = pytest.mark.django_db

TEXTO = "Hay cables expuestos en el pasillo del bloque B"


def registrar(servicio, texto=TEXTO, **cambios) -> Pedido:
    valores = {
        "canal": Canal.FORMULARIO,
        "texto": texto,
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Pasillo del bloque B",
        "contacto": None,
    }
    return servicio.registrar(DatosPedido(**(valores | cambios)))


@pytest.fixture
def pedido(servicio_vistas) -> Pedido:
    return registrar(servicio_vistas())


def detalle(client, pedido) -> str:
    respuesta = client.get(reverse("pedidos:detalle", args=[pedido.pk]))
    assert respuesta.status_code == 200
    return respuesta.content.decode()


class TestDetalle:
    def test_muestra_los_datos_del_pedido(self, client, pedido):
        html = detalle(client, pedido)
        for valor in [
            pedido.identificador,
            TEXTO,
            "Cables expuestos en el pasillo",  # descripción normalizada
            "Facultad de Ingeniería",
            "Pasillo del bloque B",
            "Formulario",
            "Electricidad",
            "Pendiente",
        ]:
            assert valor in html

    def test_muestra_todos_los_criterios_con_su_evidencia(self, client, pedido, config):
        html = detalle(client, pedido)
        for criterio in config.criterios:
            assert criterio.nombre in html
        assert "«cables expuestos»" in html
        assert "0,90" in html  # confianza
        assert "IA" in html
        assert pedido.resultado.justificacion_texto in html

    def test_muestra_el_origen_respaldo_y_los_motivos(self, client, servicio_vistas, config):
        servicio = servicio_vistas()
        servicio.principal = EvaluadorFalso(falla(), modelo="gemini-falso")
        servicio.respaldo = EvaluadorFalso(evaluacion(config, confianza=0.0))
        pedido = registrar(servicio)
        html = detalle(client, pedido)
        assert "Respaldo por palabras clave" in html
        assert "Clasificación de respaldo" in html
        assert "Requiere revisión" in html

    def test_pedido_sin_clasificacion(self, client, servicio_vistas):
        servicio = servicio_vistas()
        servicio.principal = EvaluadorFalso(falla(), modelo="gemini-falso")
        pedido = registrar(servicio)
        html = detalle(client, pedido)
        assert "Sin clasificación" in html
        assert "No se pudo clasificar el pedido" in html

    def test_escapa_el_texto_del_pedido(self, client, servicio_vistas):
        pedido = registrar(servicio_vistas(), texto="<script>alert(1)</script> se rompió")
        html = detalle(client, pedido)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_pedido_inexistente(self, client):
        respuesta = client.get(reverse("pedidos:detalle", args=[999_999]))
        assert respuesta.status_code == 404

    def test_muestra_la_recomendacion_original_y_el_historial(self, client, pedido):
        client.post(
            reverse("pedidos:corregir", args=[pedido.pk]),
            {
                "prioridad": "3",
                "tipo": "Infraestructura",
                "motivo": "Ya aislado",
                "responsable": "Ana",
            },
        )
        client.post(
            reverse("pedidos:corregir", args=[pedido.pk]),
            {
                "prioridad": "4",
                "tipo": "Infraestructura",
                "motivo": "Sin uso",
                "responsable": "Luis",
            },
        )
        html = detalle(client, pedido)
        assert "Recomendación original del sistema" in html
        original = html.split("Recomendación original del sistema", 1)[1]
        assert "P1" in original and "Electricidad" in original
        historial = html.split("Historial de correcciones", 1)[1]
        assert historial.index("Sin uso") < historial.index("Ya aislado")  # la más reciente primero
        for valor in ["Ana", "Luis", "P1", "P3", "P4"]:
            assert valor in historial


class TestConfirmar:
    def test_confirma_y_redirige(self, client, pedido):
        respuesta = client.post(
            reverse("pedidos:confirmar", args=[pedido.pk]), {"responsable": "Marta"}
        )
        assert respuesta.status_code == 302
        assert respuesta.url == reverse("pedidos:detalle", args=[pedido.pk])
        pedido.refresh_from_db()
        assert pedido.estado == EstadoPedido.VALIDADO
        assert pedido.validado_por == "Marta"

    def test_exige_el_responsable(self, client, pedido):
        respuesta = client.post(
            reverse("pedidos:confirmar", args=[pedido.pk]), {"responsable": " "}
        )
        assert respuesta.status_code == 200
        assert "El responsable es obligatorio." in respuesta.content.decode()
        pedido.refresh_from_db()
        assert pedido.estado == EstadoPedido.PENDIENTE

    def test_rechaza_un_pedido_sin_clasificacion(self, client, servicio_vistas):
        servicio = servicio_vistas()
        servicio.principal = EvaluadorFalso(falla(), modelo="gemini-falso")
        pedido = registrar(servicio)
        respuesta = client.post(
            reverse("pedidos:confirmar", args=[pedido.pk]), {"responsable": "Marta"}
        )
        assert respuesta.status_code == 400
        assert "no tiene prioridad recomendada" in respuesta.content.decode()

    def test_solo_acepta_post(self, client, pedido):
        assert client.get(reverse("pedidos:confirmar", args=[pedido.pk])).status_code == 405

    def test_pedido_inexistente(self, client):
        respuesta = client.post(reverse("pedidos:confirmar", args=[999_999]), {"responsable": "M"})
        assert respuesta.status_code == 404


class TestCorregir:
    def corregir(self, client, pedido, **cambios):
        datos = {"prioridad": "3", "tipo": "Infraestructura", "motivo": "Ya aislado"}
        datos |= {"responsable": "Marta"} | cambios
        return client.post(reverse("pedidos:corregir", args=[pedido.pk]), datos)

    def test_registra_la_correccion_y_redirige(self, client, pedido):
        respuesta = self.corregir(client, pedido)
        assert respuesta.status_code == 302
        assert respuesta.url == reverse("pedidos:detalle", args=[pedido.pk])
        correccion = CorreccionManual.objects.get()
        assert correccion.prioridad_nueva == Prioridad.P3
        pedido.refresh_from_db()
        assert pedido.corregido is True

    def test_el_motivo_es_obligatorio(self, client, pedido):
        respuesta = self.corregir(client, pedido, motivo="   ")
        assert respuesta.status_code == 200
        html = respuesta.content.decode()
        assert "El motivo es obligatorio." in html
        assert 'value="Marta"' in html  # conserva lo ingresado
        assert not CorreccionManual.objects.exists()

    def test_el_responsable_es_obligatorio(self, client, pedido):
        respuesta = self.corregir(client, pedido, responsable="")
        assert "El responsable es obligatorio." in respuesta.content.decode()
        assert not CorreccionManual.objects.exists()

    @pytest.mark.parametrize("cambios", [{"prioridad": "5"}, {"tipo": "Jardinería"}])
    def test_restringe_los_valores_a_los_configurados(self, client, pedido, cambios):
        respuesta = self.corregir(client, pedido, **cambios)
        assert respuesta.status_code == 200
        assert "Elegí una opción válida." in respuesta.content.decode()
        assert not CorreccionManual.objects.exists()

    def test_informa_si_no_cambia_nada(self, client, pedido):
        respuesta = self.corregir(client, pedido, prioridad="1", tipo="Electricidad")
        assert respuesta.status_code == 200
        assert "no cambia la prioridad ni el tipo" in respuesta.content.decode()

    def test_ofrece_las_prioridades_y_los_tipos_configurados(self, client, pedido, config):
        html = detalle(client, pedido)
        formulario = html.split('action="' + reverse("pedidos:corregir", args=[pedido.pk]), 1)[1]
        for prioridad in Prioridad:
            assert f'<option value="{prioridad.value}"' in formulario
        for tipo in config.nombres_tipos():
            assert f'<option value="{tipo}"' in formulario

    def test_recuerda_el_responsable_durante_la_sesion(self, client, pedido):
        self.corregir(client, pedido, responsable="Marta Gómez")
        html = detalle(client, pedido)
        assert html.count('value="Marta Gómez"') == 2  # confirmación y corrección
