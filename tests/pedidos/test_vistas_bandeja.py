"""Bandeja de triage (`pedidos:bandeja`)."""

import re
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from pedidos.models import EstadoPedido, Pedido
from triage.schemas import Canal

pytestmark = pytest.mark.django_db


def crear(texto: str, **cambios) -> Pedido:
    valores = {
        "canal": Canal.FORMULARIO,
        "texto_original": texto,
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Bloque B",
        "prioridad_vigente": 2,
        "tipo_vigente": "Electricidad",
        "puntaje_total": Decimal("50.00"),
        "estado": EstadoPedido.PENDIENTE,
    }
    return Pedido.objects.create(**(valores | cambios))


def filas(html: str) -> list[str]:
    cuerpo = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return re.findall(r"<tr.*?</tr>", cuerpo, flags=re.S)


def bandeja(client, **filtros) -> str:
    respuesta = client.get(reverse("pedidos:bandeja"), filtros)
    assert respuesta.status_code == 200
    return respuesta.content.decode()


def test_muestra_los_datos_de_cada_pedido(client):
    pedido = crear("x", dependencia="Rectorado", ubicacion="Hall central")
    [fila] = filas(bandeja(client))
    assert pedido.identificador in fila
    assert f'href="{reverse("pedidos:detalle", args=[pedido.pk])}"' in fila
    for valor in ["Rectorado", "Hall central", "Electricidad", "P2", "50,00", "Pendiente"]:
        assert valor in fila
    assert timezone.localtime(pedido.recibido_en).strftime("%d/%m/%Y %H:%M") in fila


def test_respeta_el_orden_de_la_bandeja(client):
    tercero = crear("p3", prioridad_vigente=3)
    sin_clasificar = crear("s", prioridad_vigente=None, tipo_vigente=None, puntaje_total=None)
    primero = crear("p1", prioridad_vigente=1, puntaje_total=Decimal("75.00"))
    segundo = crear("p2", prioridad_vigente=2)

    html = bandeja(client)
    orden = [p.identificador for p in (primero, segundo, tercero, sin_clasificar)]
    posiciones = [html.index(identificador) for identificador in orden]
    assert posiciones == sorted(posiciones)


def test_destaca_los_p1_y_los_que_requieren_revision(client):
    crear("p1", prioridad_vigente=1)
    crear("revision", prioridad_vigente=3, estado=EstadoPedido.REQUIERE_REVISION)
    crear("normal", prioridad_vigente=4)

    p1, revision, normal = filas(bandeja(client))
    assert "prioridad-p1" in p1
    assert "requiere-revision" in revision
    assert "Requiere revisión" in revision
    assert "prioridad-p1" not in normal and "requiere-revision" not in normal


def test_indica_los_valores_corregidos(client):
    crear("corregido", prioridad_vigente=1, tipo_vigente="Seguridad", corregido=True)
    crear("original")
    corregido, original = filas(bandeja(client))
    assert "corregido" in corregido and "Seguridad" in corregido and "P1" in corregido
    assert "corregido" not in original


def test_filtra_y_conserva_la_seleccion(client):
    crear("electricidad", tipo_vigente="Electricidad")
    sanitaria = crear("sanitaria", tipo_vigente="Sanitaria", dependencia="Rectorado")

    html = bandeja(client, tipo="Sanitaria", dependencia="Rectorado", prioridad="2")
    [fila] = filas(html)
    assert sanitaria.identificador in fila
    assert re.search(r'<option value="Sanitaria" selected>', html)
    assert re.search(r'<option value="Rectorado" selected>', html)
    assert re.search(r'<option value="2" selected>P2</option>', html)


def test_filtra_por_estado(client):
    crear("pendiente")
    revision = crear("revision", estado=EstadoPedido.REQUIERE_REVISION)
    [fila] = filas(bandeja(client, estado="requiere_revision"))
    assert revision.identificador in fila


def test_mensaje_sin_resultados(client):
    crear("electricidad")
    html = bandeja(client, tipo="TIC")
    assert "No hay pedidos que cumplan los filtros" in html
    assert filas(html) == []


def test_ignora_e_informa_los_filtros_invalidos(client):
    crear("uno")
    html = bandeja(client, prioridad="9", tipo="Jardinería")
    assert len(filas(html)) == 1
    assert "Se ignoraron filtros inválidos" in html
    assert "Prioridad" in html and "Tipo" in html


def test_contador_de_pedidos_sin_clasificar(client):
    crear("a", prioridad_vigente=None, tipo_vigente=None, puntaje_total=None)
    crear("b", prioridad_vigente=None, tipo_vigente=None, puntaje_total=None)
    crear("c")
    html = bandeja(client, prioridad="2")  # el contador no depende de los filtros
    assert re.search(r"Pedidos sin clasificar:\s*<strong>2</strong>", html)
