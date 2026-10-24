"""Formulario de pedido y pegado de texto libre (`pedidos:nuevo` y `pedidos:texto`)."""

import pytest
from django.urls import reverse

from pedidos import services
from pedidos.models import Pedido
from triage.schemas import Canal

pytestmark = pytest.mark.django_db

DESCRIPCION = "Hay cables expuestos en el pasillo del bloque B"


class TestFormularioDePedido:
    def test_muestra_los_campos_en_espanol(self, client):
        html = client.get(reverse("pedidos:nuevo")).content.decode()
        for etiqueta in ["Dependencia solicitante", "Ubicación", "Descripción del problema"]:
            assert etiqueta in html
        assert "Datos de contacto (opcional)" in html
        assert 'name="csrfmiddlewaretoken"' in html

    def test_rechaza_el_envio_incompleto_y_conserva_los_datos(self, client, servicio_vistas):
        respuesta = client.post(
            reverse("pedidos:nuevo"),
            {"dependencia": "  ", "ubicacion": "Aula 12", "descripcion": "", "contacto": "Ana"},
        )
        assert respuesta.status_code == 200
        html = respuesta.content.decode()
        assert "La dependencia es obligatoria." in html
        assert "La descripción del problema es obligatoria." in html
        assert 'value="Aula 12"' in html
        assert 'value="Ana"' in html
        assert not Pedido.objects.exists()

    def test_registra_prioriza_y_redirige_al_detalle(self, client, servicio_vistas):
        respuesta = client.post(
            reverse("pedidos:nuevo"),
            {
                "dependencia": "Facultad de Ingeniería",
                "ubicacion": "Bloque B",
                "descripcion": DESCRIPCION,
                "contacto": "ana@uni.edu.ar",
            },
        )
        pedido = Pedido.objects.get()
        assert respuesta.status_code == 302
        assert respuesta.url == reverse("pedidos:detalle", args=[pedido.pk])
        assert pedido.canal == Canal.FORMULARIO
        assert pedido.texto_original == DESCRIPCION
        assert pedido.contacto == "ana@uni.edu.ar"

    def test_el_detalle_muestra_el_resultado_del_registro(self, client, servicio_vistas):
        respuesta = client.post(
            reverse("pedidos:nuevo"),
            {"dependencia": "Facultad de Ingeniería", "descripcion": DESCRIPCION},
            follow=True,
        )
        pedido = Pedido.objects.get()
        html = respuesta.content.decode()
        assert f"Pedido {pedido.identificador} registrado" in html
        assert "P1" in html
        assert "Electricidad" in html
        assert pedido.resultado.justificacion_texto.split(".")[0] in html

    def test_avisa_si_el_pedido_no_pudo_priorizarse(self, client, servicio_vistas, monkeypatch):
        def explotar(*args, **kwargs):
            raise RuntimeError("falla")

        monkeypatch.setattr(services, "triar_pedido", explotar)
        respuesta = client.post(
            reverse("pedidos:nuevo"),
            {"dependencia": "Rectorado", "descripcion": DESCRIPCION},
            follow=True,
        )
        assert "El pedido se registró pero no pudo priorizarse" in respuesta.content.decode()
        assert Pedido.objects.count() == 1


class TestPegadoDeTextoLibre:
    def test_muestra_el_texto_y_la_dependencia_opcional(self, client):
        html = client.get(reverse("pedidos:texto")).content.decode()
        assert "Texto del correo o nota" in html
        assert "Dependencia (opcional)" in html

    @pytest.mark.parametrize("texto", ["", "    ", "\n\t "])
    def test_rechaza_el_texto_vacio(self, client, servicio_vistas, texto):
        respuesta = client.post(reverse("pedidos:texto"), {"texto": texto})
        assert respuesta.status_code == 200
        assert "El texto no puede estar vacío." in respuesta.content.decode()
        assert not Pedido.objects.exists()

    def test_registra_con_el_texto_integro_y_redirige(self, client, servicio_vistas):
        texto = "  De: Bedelía\n\nSe cortó la luz en el aula 12.  "
        respuesta = client.post(reverse("pedidos:texto"), {"texto": texto, "dependencia": ""})
        pedido = Pedido.objects.get()
        assert respuesta.url == reverse("pedidos:detalle", args=[pedido.pk])
        assert pedido.canal == Canal.TEXTO_LIBRE
        assert pedido.texto_original == texto
        assert pedido.contacto is None

    def test_usa_la_dependencia_indicada(self, client, servicio_vistas):
        client.post(reverse("pedidos:texto"), {"texto": DESCRIPCION, "dependencia": "Rectorado"})
        assert Pedido.objects.get().dependencia == "Rectorado"
