"""Recorridos de punta a punta por la interfaz web (tarea 9.1).

Se usan los evaluadores reales: `EvaluadorGemini` con un transporte HTTP simulado (nunca se
contacta a Gemini) y `EvaluadorPalabrasClave` como respaldo, con la configuración institucional.
"""

import json

import httpx
import pytest
from django.urls import reverse

from pedidos import views
from pedidos.models import EstadoPedido, Pedido
from pedidos.services import ServicioPedidos
from triage.evaluadores.gemini import EvaluadorGemini
from triage.evaluadores.palabras_clave import EvaluadorPalabrasClave
from triage.justificacion import AVISO_RESPALDO, TEXTO_SIN_CLASIFICACION
from triage.schemas import OrigenResultado, Prioridad

pytestmark = pytest.mark.django_db

CORREO = "ana.perez@uni.edu.ar"
TELEFONO = "351 555 1234"
CONTACTO = f"Ana Pérez, {TELEFONO}"
DESCRIPCION = (
    "Hay cables pelados en el pasillo del bloque B y mañana hay examen. "
    f"Avisar a {CORREO} o al {TELEFONO}."
)
FORMULARIO = {
    "dependencia": "Facultad de Ingeniería",
    "ubicacion": "Pasillo del bloque B",
    "descripcion": DESCRIPCION,
    "contacto": CONTACTO,
}


def respuesta_ia(config) -> httpx.Response:
    criterios = {c: {"puntaje": 0, "evidencia": []} for c in config.claves_criterios()}
    criterios["riesgo_personas"] = {"puntaje": 3, "evidencia": ["cables pelados en el pasillo"]}
    criterios["impacto_academico"] = {"puntaje": 2, "evidencia": ["mañana hay examen"]}
    evaluacion = {
        "descripcion_normalizada": "Cables pelados en el pasillo del bloque B",
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Pasillo del bloque B",
        "tipo_principal": "Electricidad",
        "tipos_secundarios": [],
        "criterios": criterios,
        "confianza": 0.92,
        "texto_insuficiente": False,
        "conflicto_tipos": False,
    }
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": json.dumps(evaluacion)}]},
                    "finishReason": "STOP",
                }
            ]
        },
    )


class Gemini:
    """Transporte que simula a Gemini y guarda cada request que sale hacia la IA."""

    def __init__(self, responder):
        self.responder = responder
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request)


@pytest.fixture
def usar_evaluadores(monkeypatch, config):
    """Hace que las vistas usen los evaluadores reales con el transporte indicado."""

    def _usar(transporte: Gemini | None, api_key: str | None = "clave-de-prueba") -> None:
        cliente = httpx.Client(transport=httpx.MockTransport(transporte)) if transporte else None
        gemini = EvaluadorGemini(
            config, api_key=api_key, modelo="gemini-de-prueba", http_client=cliente
        )
        servicio = ServicioPedidos(config, gemini, EvaluadorPalabrasClave(config))
        monkeypatch.setattr(views, "obtener_servicio", lambda: servicio)

    return _usar


def html(respuesta) -> str:
    assert respuesta.status_code == 200
    return respuesta.content.decode()


def fila_de(bandeja: str, pedido: Pedido) -> str:
    """El `<tr>` de la bandeja que contiene al pedido."""
    posicion = bandeja.index(pedido.identificador)
    return bandeja[bandeja.rindex("<tr", 0, posicion) : bandeja.index("</tr>", posicion)]


class TestRecorridoCompleto:
    def test_registrar_ver_en_bandeja_corregir_y_ver_el_historial(
        self, client, config, usar_evaluadores
    ):
        usar_evaluadores(Gemini(lambda _: respuesta_ia(config)))

        # Registrar por formulario: redirige al detalle con prioridad, tipo y justificación.
        respuesta = client.post(reverse("pedidos:nuevo"), FORMULARIO, follow=True)
        pedido = Pedido.objects.get()
        assert respuesta.redirect_chain == [(reverse("pedidos:detalle", args=[pedido.pk]), 302)]
        detalle = html(respuesta)
        assert pedido.prioridad_vigente == Prioridad.P1
        assert pedido.resultado.origen == OrigenResultado.IA
        assert f"Pedido {pedido.identificador} registrado: prioridad P1, tipo Electricidad" in (
            detalle
        )
        assert pedido.resultado.justificacion_texto in detalle

        # En la bandeja aparece con su prioridad, destacado como P1 y sin marca de corregido.
        fila = fila_de(html(client.get(reverse("pedidos:bandeja"))), pedido)
        assert "P1" in fila and "Electricidad" in fila
        assert "etiqueta-corregido" not in fila

        # Corregir desde el detalle.
        respuesta = client.post(
            reverse("pedidos:corregir", args=[pedido.pk]),
            {
                "prioridad": "2",
                "tipo": "Infraestructura",
                "motivo": "Los cables están entubados; no hay riesgo inmediato",
                "responsable": "Jefatura de mantenimiento",
            },
            follow=True,
        )
        detalle = html(respuesta)
        assert f"Corrección del pedido {pedido.identificador} registrada." in detalle
        assert "Historial de correcciones" in detalle
        assert "Los cables están entubados; no hay riesgo inmediato" in detalle
        assert "Recomendación original del sistema" in detalle

        pedido.refresh_from_db()
        assert (pedido.prioridad_vigente, pedido.tipo_vigente) == (Prioridad.P2, "Infraestructura")
        assert pedido.estado == EstadoPedido.VALIDADO
        assert pedido.resultado.prioridad_final == Prioridad.P1  # la recomendación queda intacta

        # La bandeja muestra el valor corregido con su marca.
        fila = fila_de(html(client.get(reverse("pedidos:bandeja"))), pedido)
        assert "P2" in fila and "Infraestructura" in fila
        assert "etiqueta-corregido" in fila


class TestIaNoDisponible:
    @pytest.mark.parametrize(
        ("transporte", "api_key"),
        [
            (None, None),  # sin GEMINI_API_KEY: pasa directo al respaldo
            (Gemini(lambda _: httpx.Response(503, json={"error": {"code": 503}})), "clave"),
        ],
        ids=["sin_configurar", "servicio_caido"],
    )
    def test_clasifica_por_respaldo_y_requiere_revision(
        self, client, usar_evaluadores, transporte, api_key
    ):
        usar_evaluadores(transporte, api_key=api_key)

        detalle = html(client.post(reverse("pedidos:nuevo"), FORMULARIO, follow=True))
        pedido = Pedido.objects.get()
        assert pedido.resultado.origen == OrigenResultado.RESPALDO
        assert pedido.tipo_vigente == "Electricidad"
        assert pedido.prioridad_vigente is not None
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert "clasificacion_respaldo" in pedido.motivos_revision
        assert pedido.resultado.justificacion_texto.startswith(AVISO_RESPALDO)
        assert AVISO_RESPALDO in detalle
        assert "Respaldo por palabras clave" in detalle

        fila = fila_de(html(client.get(reverse("pedidos:bandeja"))), pedido)
        assert "requiere-revision" in fila


class TestAmbosEvaluadoresFallan:
    def test_queda_registrado_sin_clasificar_y_visible_en_la_bandeja(
        self, client, usar_evaluadores
    ):
        usar_evaluadores(Gemini(lambda _: httpx.Response(500, json={"error": {"code": 500}})))
        texto = "Necesitamos que alguien venga a ver lo que pasó ayer, por favor."

        respuesta = client.post(reverse("pedidos:texto"), {"texto": texto}, follow=True)
        detalle = html(respuesta)
        pedido = Pedido.objects.get()
        assert pedido.texto_original == texto
        assert pedido.prioridad_vigente is None and pedido.tipo_vigente is None
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert pedido.resultado.origen == OrigenResultado.SIN_CLASIFICACION
        assert pedido.resultado.intentos_ia == 2  # intento original y un único reintento
        assert "registrado sin clasificación" in detalle
        assert TEXTO_SIN_CLASIFICACION in detalle

        bandeja = html(client.get(reverse("pedidos:bandeja")))
        fila = fila_de(bandeja, pedido)
        assert "requiere-revision" in fila
        assert "Pedidos sin clasificar: <strong>1</strong>" in bandeja


class TestPrivacidad:
    def test_los_datos_de_contacto_nunca_llegan_a_la_request_hacia_la_ia(
        self, client, config, usar_evaluadores
    ):
        # La primera llamada falla para que también se inspeccione el reintento.
        llamadas = iter([httpx.Response(503, json={"error": {"code": 503}}), respuesta_ia(config)])
        gemini = Gemini(lambda _: next(llamadas))
        usar_evaluadores(gemini)

        client.post(reverse("pedidos:nuevo"), FORMULARIO)

        assert len(gemini.requests) == 2
        for request in gemini.requests:
            # La URL, el cuerpo tal como viaja y el cuerpo decodificado (sin escapes \\uXXXX).
            cuerpo = json.dumps(json.loads(request.content), ensure_ascii=False)
            enviado = f"{request.url} {request.content.decode()} {cuerpo}"
            for dato in [CORREO, TELEFONO, "Ana Pérez"]:
                assert dato not in enviado
            assert "[correo]" in enviado and "[telefono]" in enviado
        # El contacto se conserva en la base, solo para uso interno.
        assert Pedido.objects.get().contacto == CONTACTO
