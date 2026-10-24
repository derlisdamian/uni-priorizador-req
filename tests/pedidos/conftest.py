"""Fixtures compartidas por los tests de la app `pedidos`."""

import pytest

from pedidos import configuracion
from pedidos.services import ServicioPedidos
from triage.config import ConfiguracionTriage
from triage.evaluadores import ErrorEvaluacion, TipoErrorEvaluacion
from triage.schemas import EntradaEvaluacion, EvaluacionCriterios, PuntajeCriterio


@pytest.fixture
def config() -> ConfiguracionTriage:
    return configuracion.obtener()


def evaluacion(config: ConfiguracionTriage, *, puntajes=None, **cambios) -> EvaluacionCriterios:
    """Evaluación válida; por defecto riesgo_personas = 3 (P1 por escalamiento)."""
    puntajes = {"riesgo_personas": 3} if puntajes is None else puntajes
    criterios = {
        clave: PuntajeCriterio(
            puntaje=puntajes.get(clave, 0),
            evidencia=["cables expuestos"] if puntajes.get(clave, 0) >= 2 else [],
        )
        for clave in config.claves_criterios()
    }
    valores = {
        "descripcion_normalizada": "Cables expuestos en el pasillo",
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Pasillo del bloque B",
        "tipo_principal": "Electricidad",
        "tipos_secundarios": [],
        "criterios": criterios,
        "confianza": 0.9,
        "texto_insuficiente": False,
        "conflicto_tipos": False,
    }
    return EvaluacionCriterios(**(valores | cambios))


class EvaluadorFalso:
    """Devuelve siempre la misma respuesta (una evaluación o una excepción) y anota las entradas."""

    def __init__(self, respuesta, nombre="falso", modelo=None):
        self.respuesta = respuesta
        self.entradas: list[EntradaEvaluacion] = []
        self._nombre = nombre
        if modelo is not None:
            self.modelo = modelo

    @property
    def nombre(self) -> str:
        return self._nombre

    def evaluar(self, entrada: EntradaEvaluacion) -> EvaluacionCriterios:
        self.entradas.append(entrada)
        if isinstance(self.respuesta, BaseException):
            raise self.respuesta
        return self.respuesta


def falla(tipo=TipoErrorEvaluacion.SERVICIO, detalle="Gemini respondió 503") -> ErrorEvaluacion:
    return ErrorEvaluacion(tipo, detalle)


@pytest.fixture
def construir_servicio(config):
    """Crea un `ServicioPedidos` con evaluadores falsos (por defecto, la IA responde P1)."""

    def _construir(principal=None, respaldo=None, config_servicio=None) -> ServicioPedidos:
        cfg = config_servicio or config
        principal = principal or EvaluadorFalso(evaluacion(cfg), modelo="gemini-falso")
        respaldo = respaldo or EvaluadorFalso(
            falla(TipoErrorEvaluacion.SIN_COINCIDENCIAS, "ningún tipo"), nombre="palabras_clave"
        )
        return ServicioPedidos(cfg, principal, respaldo)

    return _construir


@pytest.fixture
def servicio_vistas(monkeypatch, construir_servicio):
    """Hace que las vistas usen un servicio con evaluadores falsos (la IA responde P1)."""
    from pedidos import views

    def _usar(servicio=None):
        servicio = servicio or construir_servicio()
        monkeypatch.setattr(views, "obtener_servicio", lambda: servicio)
        return servicio

    _usar()
    return _usar
