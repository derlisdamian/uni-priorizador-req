"""Estructura base de la interfaz: rutas con espacio de nombres, navegación y mensajes."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_la_raiz_redirige_a_la_bandeja(client):
    respuesta = client.get("/")
    assert respuesta.status_code == 302
    assert respuesta.url == reverse("pedidos:bandeja")


@pytest.mark.parametrize(
    ("nombre", "ruta"),
    [
        ("pedidos:bandeja", "/pedidos/"),
        ("pedidos:nuevo", "/pedidos/nuevo/"),
        ("pedidos:texto", "/pedidos/texto/"),
        ("pedidos:detalle", "/pedidos/7/"),
        ("pedidos:confirmar", "/pedidos/7/confirmar/"),
        ("pedidos:corregir", "/pedidos/7/corregir/"),
    ],
)
def test_rutas_con_espacio_de_nombres(nombre, ruta):
    argumentos = [7] if "7" in ruta else []
    assert reverse(nombre, args=argumentos) == ruta


@pytest.mark.parametrize("nombre", ["pedidos:bandeja", "pedidos:nuevo", "pedidos:texto"])
def test_la_plantilla_base_tiene_navegacion_y_estilos(client, nombre):
    html = client.get(reverse(nombre)).content.decode()
    assert '<html lang="es"' in html
    assert "pico" in html  # estilos livianos por CDN
    for destino, texto in [
        ("pedidos:bandeja", "Bandeja"),
        ("pedidos:nuevo", "Nuevo pedido"),
        ("pedidos:texto", "Pegar texto"),
    ]:
        assert f'href="{reverse(destino)}"' in html
        assert texto in html


def test_muestra_los_mensajes_de_la_aplicacion(client, servicio_vistas):
    respuesta = client.post(
        reverse("pedidos:texto"), {"texto": "Hay cables expuestos en el pasillo"}, follow=True
    )
    assert 'role="alert"' in respuesta.content.decode()
