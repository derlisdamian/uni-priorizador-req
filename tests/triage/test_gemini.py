"""Evaluador con Gemini según el contrato REST generateContent (`triage.evaluadores.gemini`).

Las llamadas pasan por un transporte HTTP simulado: nunca se contacta a Gemini.
"""

import json
from pathlib import Path

import httpx
import pytest

from triage.config import ConfiguracionTriage, cargar_configuracion
from triage.evaluadores import ErrorEvaluacion, EvaluadorPedidos, TipoErrorEvaluacion
from triage.evaluadores.gemini import (
    EvaluadorGemini,
    cargar_prompt,
    construir_schema_respuesta,
)
from triage.schemas import Canal, EntradaEvaluacion

DIRECTORIO_INICIAL = Path(__file__).resolve().parents[2] / "config"
API_KEY = "clave-de-prueba-123"
MODELO = "gemini-de-prueba"
URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

TEXTO = (
    "Hay cables pelados en el pasillo del 2º piso del Pabellón Central. "
    "Mañana hay examen en el aula 12. Escribir a [correo]."
)


@pytest.fixture(scope="module")
def config() -> ConfiguracionTriage:
    return cargar_configuracion(DIRECTORIO_INICIAL)


@pytest.fixture
def entrada() -> EntradaEvaluacion:
    return EntradaEvaluacion(
        texto=TEXTO,
        canal=Canal.TEXTO_LIBRE,
        dependencia_informada="Facultad de Ingeniería",
        ubicacion_informada=None,
    )


def evaluacion_json(config: ConfiguracionTriage, **cambios) -> dict:
    criterios = {c: {"puntaje": 0, "evidencia": []} for c in config.claves_criterios()}
    criterios |= {
        "riesgo_personas": {"puntaje": 3, "evidencia": ["cables pelados en el pasillo"]},
        "impacto_academico": {"puntaje": 3, "evidencia": ["Mañana hay examen"]},
    }
    datos = {
        "descripcion_normalizada": "Cables pelados en el pasillo del 2º piso",
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Pasillo del 2º piso, Pabellón Central",
        "tipo_principal": "Electricidad",
        "tipos_secundarios": [],
        "criterios": criterios,
        "confianza": 0.9,
        "texto_insuficiente": False,
        "conflicto_tipos": False,
    }
    return datos | cambios


def respuesta_gemini(texto: str, finish_reason: str = "STOP") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": texto}]},
                    "finishReason": finish_reason,
                }
            ]
        },
    )


class Transporte:
    """Transporte httpx simulado que registra las requests y devuelve respuestas fijas."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    @property
    def cuerpo(self) -> dict:
        return json.loads(self.requests[-1].content)


def crear_evaluador(config, transporte, **opciones) -> EvaluadorGemini:
    parametros = {"api_key": API_KEY, "modelo": MODELO} | opciones
    return EvaluadorGemini(
        config, http_client=httpx.Client(transport=httpx.MockTransport(transporte)), **parametros
    )


def error_al_evaluar(evaluador, entrada) -> ErrorEvaluacion:
    with pytest.raises(ErrorEvaluacion) as excinfo:
        evaluador.evaluar(entrada)
    assert API_KEY not in excinfo.value.detalle
    return excinfo.value


@pytest.fixture
def exitoso(config):
    return Transporte(respuesta_gemini(json.dumps(evaluacion_json(config))))


# --- Prompt ---


def test_el_prompt_versionado_incluye_escala_criterios_tipos_y_senales(config):
    prompt = cargar_prompt(config)
    assert prompt.version
    assert "$" not in prompt.texto
    for valor in ("0", "1", "2", "3"):
        assert valor in prompt.texto
    for criterio in config.criterios:
        assert criterio.clave in prompt.texto
        assert criterio.nombre in prompt.texto
    for tipo in config.tipos:
        assert tipo.nombre in prompt.texto
        for senal in tipo.senales:
            assert senal in prompt.texto


def test_el_prompt_pide_evidencia_literal_y_extraer_dependencia_y_ubicacion(config):
    texto = cargar_prompt(config).texto.lower()
    assert "literal" in texto
    assert "dependencia" in texto
    assert "ubicación" in texto


# --- Schema de respuesta ---


def test_el_schema_enumera_los_tipos_configurados(config):
    schema = construir_schema_respuesta(config)
    propiedades = schema["properties"]
    assert propiedades["tipo_principal"]["enum"] == config.nombres_tipos()
    assert propiedades["tipos_secundarios"]["items"]["enum"] == config.nombres_tipos()


def test_el_schema_tiene_una_propiedad_fija_por_criterio(config):
    criterios = construir_schema_respuesta(config)["properties"]["criterios"]
    assert list(criterios["properties"]) == config.claves_criterios()
    assert criterios["required"] == config.claves_criterios()
    for definicion in criterios["properties"].values():
        assert definicion["properties"]["puntaje"]["enum"] == [0, 1, 2, 3]
        assert definicion["properties"]["evidencia"]["maxItems"] == 3
        assert definicion["required"] == ["puntaje", "evidencia"]


def test_el_schema_limita_la_confianza_y_exige_todos_los_campos(config):
    schema = construir_schema_respuesta(config)
    assert schema["properties"]["confianza"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert schema["required"] == list(schema["properties"])


def test_el_schema_es_plano_salvo_los_campos_nulables(config):
    texto = json.dumps(construir_schema_respuesta(config))
    assert "$ref" not in texto
    assert "$defs" not in texto
    propiedades = construir_schema_respuesta(config)["properties"]
    con_any_of = [nombre for nombre, valor in propiedades.items() if "anyOf" in valor]
    assert con_any_of == ["dependencia", "ubicacion"]


# --- Request ---


def test_cumple_el_puerto_y_se_identifica_con_el_modelo(config, exitoso):
    evaluador = crear_evaluador(config, exitoso)
    assert isinstance(evaluador, EvaluadorPedidos)
    assert evaluador.nombre == f"gemini:{MODELO}"
    assert evaluador.modelo == MODELO
    assert evaluador.version_prompt == cargar_prompt(config).version


def test_llama_por_post_al_endpoint_generate_content_del_modelo_configurado(
    config, exitoso, entrada
):
    crear_evaluador(config, exitoso).evaluar(entrada)
    request = exitoso.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{URL_BASE}/{MODELO}:generateContent"


def test_el_modelo_sale_de_la_configuracion(config, entrada):
    transporte = Transporte(respuesta_gemini(json.dumps(evaluacion_json(config))))
    crear_evaluador(config, transporte, modelo="gemini-flash-latest").evaluar(entrada)
    assert transporte.requests[0].url.path.endswith("/gemini-flash-latest:generateContent")


def test_la_api_key_va_solo_en_el_header(config, exitoso, entrada):
    crear_evaluador(config, exitoso).evaluar(entrada)
    request = exitoso.requests[0]
    assert request.headers["x-goog-api-key"] == API_KEY
    assert "key=" not in str(request.url)
    assert API_KEY not in request.content.decode()


def test_el_cuerpo_tiene_un_unico_contenido_instrucciones_y_configuracion(config, exitoso, entrada):
    crear_evaluador(config, exitoso).evaluar(entrada)
    cuerpo = exitoso.cuerpo
    assert len(cuerpo["contents"]) == 1
    assert len(cuerpo["contents"][0]["parts"]) == 1
    assert cuerpo["systemInstruction"]["parts"] == [{"text": cargar_prompt(config).texto}]
    assert cuerpo["generationConfig"] == {
        "temperature": 0,
        "responseMimeType": "application/json",
        "responseJsonSchema": construir_schema_respuesta(config),
    }


def test_el_texto_enviado_es_la_entrada_delimitada_sin_datos_de_contacto(config, exitoso, entrada):
    crear_evaluador(config, exitoso).evaluar(entrada)
    texto = exitoso.cuerpo["contents"][0]["parts"][0]["text"]
    inicio, fin = texto.index("<pedido>"), texto.index("</pedido>")
    enviado = json.loads(texto[inicio + len("<pedido>") : fin])
    assert enviado == entrada.model_dump(mode="json")
    assert set(enviado) == {"texto", "canal", "dependencia_informada", "ubicacion_informada"}
    assert "contacto" not in texto


@pytest.mark.parametrize(("timeout_s", "esperado"), [(None, 4.0), (2.5, 2.5)])
def test_aplica_el_timeout_configurado(config, entrada, timeout_s, esperado):
    transporte = Transporte(respuesta_gemini(json.dumps(evaluacion_json(config))))
    opciones = {} if timeout_s is None else {"timeout_s": timeout_s}
    crear_evaluador(config, transporte, **opciones).evaluar(entrada)
    assert transporte.requests[0].extensions["timeout"]["read"] == esperado


# --- Lectura de la respuesta ---


def test_devuelve_la_evaluacion_del_primer_candidato(config, exitoso, entrada):
    evaluacion = crear_evaluador(config, exitoso).evaluar(entrada)
    assert evaluacion.tipo_principal == "Electricidad"
    assert evaluacion.criterios["riesgo_personas"].puntaje == 3
    assert evaluacion.criterios["impacto_academico"].evidencia == ["Mañana hay examen"]
    assert evaluacion.confianza == 0.9


def test_la_respuesta_pasa_por_el_validador_que_descarta_la_evidencia_inventada(config, entrada):
    datos = evaluacion_json(config)
    datos["criterios"]["urgencia_temporal"] = {"puntaje": 1, "evidencia": ["es para ayer"]}
    transporte = Transporte(respuesta_gemini(json.dumps(datos)))
    evaluacion = crear_evaluador(config, transporte).evaluar(entrada)
    assert evaluacion.criterios["urgencia_temporal"].evidencia == []


@pytest.mark.parametrize(
    "respuesta",
    [
        pytest.param(respuesta_gemini("no es JSON"), id="json-invalido"),
        pytest.param(respuesta_gemini('{"tipo_principal": "Electricidad"}'), id="campos-faltantes"),
        pytest.param(respuesta_gemini("{}", finish_reason="SAFETY"), id="finish-safety"),
        pytest.param(respuesta_gemini("{}", finish_reason="MAX_TOKENS"), id="finish-max-tokens"),
        pytest.param(httpx.Response(200, json={"candidates": []}), id="sin-candidatos"),
        pytest.param(
            httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
            id="bloqueado",
        ),
        pytest.param(
            httpx.Response(
                200, json={"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}
            ),
            id="sin-partes",
        ),
    ],
)
def test_respuestas_inutilizables_son_respuesta_invalida(config, entrada, respuesta):
    evaluador = crear_evaluador(config, Transporte(respuesta))
    assert error_al_evaluar(evaluador, entrada).tipo is TipoErrorEvaluacion.RESPUESTA_INVALIDA


def test_una_evaluacion_rechazada_por_el_validador_es_respuesta_invalida(config, entrada):
    datos = evaluacion_json(config, tipo_principal="Jardinería")
    evaluador = crear_evaluador(config, Transporte(respuesta_gemini(json.dumps(datos))))
    error = error_al_evaluar(evaluador, entrada)
    assert error.tipo is TipoErrorEvaluacion.RESPUESTA_INVALIDA
    assert "Jardinería" in error.detalle


# --- Traducción de errores ---


@pytest.mark.parametrize("estado", [400, 429, 500, 503])
def test_los_errores_http_son_errores_de_servicio_sin_reintentos(config, entrada, estado):
    transporte = Transporte(
        httpx.Response(estado, json={"error": {"code": estado, "message": "falla"}}),
        respuesta_gemini(json.dumps(evaluacion_json(config))),
    )
    error = error_al_evaluar(crear_evaluador(config, transporte), entrada)
    assert error.tipo is TipoErrorEvaluacion.SERVICIO
    assert str(estado) in error.detalle
    assert len(transporte.requests) == 1


def test_el_timeout_de_la_red_es_error_de_timeout(config, entrada):
    transporte = Transporte(httpx.ReadTimeout("lento"), httpx.ReadTimeout("lento"))
    error = error_al_evaluar(crear_evaluador(config, transporte), entrada)
    assert error.tipo is TipoErrorEvaluacion.TIMEOUT
    assert len(transporte.requests) == 1


def test_una_falla_de_conexion_es_error_de_servicio(config, entrada):
    transporte = Transporte(httpx.ConnectError("sin red"), httpx.ConnectError("sin red"))
    error = error_al_evaluar(crear_evaluador(config, transporte), entrada)
    assert error.tipo is TipoErrorEvaluacion.SERVICIO
    assert len(transporte.requests) == 1


@pytest.mark.parametrize("api_key", ["", None])
def test_sin_api_key_no_esta_configurado_y_no_llama_a_la_red(config, entrada, api_key):
    transporte = Transporte()
    evaluador = crear_evaluador(config, transporte, api_key=api_key)
    error = error_al_evaluar(evaluador, entrada)
    assert error.tipo is TipoErrorEvaluacion.NO_CONFIGURADO
    assert transporte.requests == []
