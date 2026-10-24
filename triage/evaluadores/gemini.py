"""Evaluador con Gemini mediante el endpoint REST `generateContent` (SDK `google-genai`).

Contrato normativo: `POST v1beta/models/{modelo}:generateContent` con la API key solo en el
header `X-goog-api-key`, un único contenido sin historial, `systemInstruction` y
`generationConfig` (temperatura 0 y salida JSON con schema).
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from triage.config import ConfiguracionTriage
from triage.evaluadores import ErrorEvaluacion, TipoErrorEvaluacion
from triage.schemas import EntradaEvaluacion, EvaluacionCriterios
from triage.validacion import EvaluacionInvalida, validar_evaluacion

ARCHIVO_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "evaluar_pedido.md"
TIMEOUT_POR_DEFECTO_S = 9.0  # gemini-3.8-flash tarda 6–8 s; con reintento el peor caso ronda 18 s
# Gemini rechaza con 400 INVALID_ARGUMENT un plazo del servidor menor que 10 s.
PLAZO_MINIMO_SERVIDOR_S = 10
MAX_EVIDENCIA = 3
_VERSION = re.compile(r"\A<!--\s*version:\s*(?P<version>\S+)\s*-->\s*\n")


@dataclass(frozen=True)
class Prompt:
    version: str
    texto: str


def cargar_prompt(config: ConfiguracionTriage, archivo: Path = ARCHIVO_PROMPT) -> Prompt:
    """Lee el prompt versionado y lo completa con los criterios y los tipos configurados."""
    contenido = archivo.read_text(encoding="utf-8")
    encabezado = _VERSION.match(contenido)
    if encabezado is None:
        raise ValueError(f"{archivo.name}: falta el encabezado <!-- version: ... -->")
    criterios = "\n".join(
        f"- `{c.clave}` ({c.nombre})"
        + (": informativo, no suma a la prioridad" if c.informativo else "")
        for c in config.criterios
    )
    tipos = "\n".join(f"- {t.nombre}: {', '.join(t.senales)}" for t in config.tipos)
    texto = Template(contenido[encabezado.end() :]).substitute(criterios=criterios, tipos=tipos)
    return Prompt(version=encabezado["version"], texto=texto.strip())


def _texto_nulable() -> dict[str, object]:
    return {"anyOf": [{"type": "string"}, {"type": "null"}]}


def construir_schema_respuesta(config: ConfiguracionTriage) -> dict[str, object]:
    """JSON Schema plano de la respuesta, con los tipos y los criterios de la configuración."""
    tipos = config.nombres_tipos()
    criterio = {
        "type": "object",
        "properties": {
            "puntaje": {"type": "integer", "enum": [0, 1, 2, 3]},
            "evidencia": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_EVIDENCIA},
        },
        "required": ["puntaje", "evidencia"],
    }
    propiedades = {
        "descripcion_normalizada": {"type": "string"},
        "dependencia": _texto_nulable(),
        "ubicacion": _texto_nulable(),
        "tipo_principal": {"type": "string", "enum": tipos},
        "tipos_secundarios": {"type": "array", "items": {"type": "string", "enum": tipos}},
        "criterios": {
            "type": "object",
            "properties": {clave: criterio for clave in config.claves_criterios()},
            "required": config.claves_criterios(),
        },
        "confianza": {"type": "number", "minimum": 0, "maximum": 1},
        "texto_insuficiente": {"type": "boolean"},
        "conflicto_tipos": {"type": "boolean"},
    }
    return {"type": "object", "properties": propiedades, "required": list(propiedades)}


def _plazo_servidor(timeout_s: float) -> int:
    return max(PLAZO_MINIMO_SERVIDOR_S, math.ceil(timeout_s))


def _contenido_pedido(entrada: EntradaEvaluacion) -> str:
    return f"<pedido>{entrada.model_dump_json()}</pedido>"


def _invalida(detalle: str) -> ErrorEvaluacion:
    return ErrorEvaluacion(TipoErrorEvaluacion.RESPUESTA_INVALIDA, detalle)


def _texto_respuesta(respuesta: types.GenerateContentResponse) -> str:
    """Toma `candidates[0].content.parts[0].text` o rechaza la respuesta."""
    feedback = respuesta.prompt_feedback
    if feedback is not None and feedback.block_reason is not None:
        raise _invalida(f"pedido bloqueado por Gemini ({feedback.block_reason})")
    if not respuesta.candidates:
        raise _invalida("la respuesta no tiene candidatos")
    candidato = respuesta.candidates[0]
    if candidato.finish_reason != types.FinishReason.STOP:
        raise _invalida(f"finalización inesperada ({candidato.finish_reason})")
    partes = candidato.content.parts if candidato.content else None
    if not partes or not partes[0].text:
        raise _invalida("el candidato no tiene texto")
    return partes[0].text


class EvaluadorGemini:
    def __init__(
        self,
        config: ConfiguracionTriage,
        *,
        api_key: str | None,
        modelo: str,
        timeout_s: float = TIMEOUT_POR_DEFECTO_S,
        http_client: httpx.Client | None = None,
    ):
        self.config = config
        self.modelo = modelo
        self._prompt = cargar_prompt(config)
        self._schema = construir_schema_respuesta(config)
        # Sin API key no se crea el cliente: se informa NO_CONFIGURADO sin tocar la red.
        self._cliente = (
            genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=round(timeout_s * 1000),  # milisegundos, lo corta el cliente
                    # Sin este header el SDK envía el timeout como plazo del servidor.
                    headers={"X-Server-Timeout": str(_plazo_servidor(timeout_s))},
                    retry_options=types.HttpRetryOptions(attempts=1),  # el pipeline reintenta
                    httpx_client=http_client,
                ),
            )
            if api_key
            else None
        )

    @property
    def nombre(self) -> str:
        return f"gemini:{self.modelo}"

    @property
    def version_prompt(self) -> str:
        return self._prompt.version

    def _generar(self, entrada: EntradaEvaluacion) -> types.GenerateContentResponse:
        if self._cliente is None:
            raise ErrorEvaluacion(
                TipoErrorEvaluacion.NO_CONFIGURADO, "falta la variable GEMINI_API_KEY"
            )
        try:
            return self._cliente.models.generate_content(
                model=self.modelo,
                contents=_contenido_pedido(entrada),
                config=types.GenerateContentConfig(
                    system_instruction=self._prompt.texto,
                    temperature=0,
                    response_mime_type="application/json",
                    response_json_schema=self._schema,
                ),
            )
        except errors.APIError as error:
            raise ErrorEvaluacion(
                TipoErrorEvaluacion.SERVICIO, f"Gemini respondió {error.code} {error.status}"
            ) from error
        except httpx.TimeoutException as error:
            raise ErrorEvaluacion(
                TipoErrorEvaluacion.TIMEOUT,
                f"Gemini no respondió a tiempo ({type(error).__name__})",
            ) from error
        except httpx.HTTPError as error:
            raise ErrorEvaluacion(
                TipoErrorEvaluacion.SERVICIO, f"falla de red con Gemini ({type(error).__name__})"
            ) from error

    def evaluar(self, entrada: EntradaEvaluacion) -> EvaluacionCriterios:
        texto = _texto_respuesta(self._generar(entrada))
        try:
            candidata = EvaluacionCriterios.model_validate_json(texto)
            return validar_evaluacion(candidata, entrada.texto, self.config)
        except ValidationError as error:
            raise _invalida(
                f"la respuesta no cumple el schema ({error.error_count()} errores)"
            ) from error
        except EvaluacionInvalida as error:
            raise _invalida("; ".join(error.motivos)) from error
