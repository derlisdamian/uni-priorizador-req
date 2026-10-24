"""Orquestación del triage con reintento, respaldo y revisión (`triage.pipeline`)."""

from pathlib import Path

import pytest

from triage.config import ConfiguracionTriage, cargar_configuracion
from triage.evaluadores import ErrorEvaluacion, TipoErrorEvaluacion
from triage.justificacion import AVISO_RESPALDO, TEXTO_SIN_CLASIFICACION
from triage.pipeline import anonimizar_texto, construir_entrada, triar_pedido
from triage.schemas import (
    Canal,
    EntradaEvaluacion,
    EvaluacionCriterios,
    MotivoRevision,
    OrigenResultado,
    Prioridad,
    PuntajeCriterio,
)

DIRECTORIO_INICIAL = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def config() -> ConfiguracionTriage:
    return cargar_configuracion(DIRECTORIO_INICIAL)


def evaluacion(config, **cambios) -> EvaluacionCriterios:
    criterios = {
        clave: PuntajeCriterio(puntaje=0, evidencia=[]) for clave in config.claves_criterios()
    }
    criterios["riesgo_personas"] = PuntajeCriterio(puntaje=3, evidencia=["cables expuestos"])
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
    """Devuelve, en orden, cada respuesta programada: una evaluación o una excepción."""

    def __init__(self, *respuestas, nombre="falso", modelo=None):
        self.respuestas = list(respuestas)
        self.entradas: list[EntradaEvaluacion] = []
        self._nombre = nombre
        if modelo is not None:
            self.modelo = modelo

    @property
    def nombre(self) -> str:
        return self._nombre

    def evaluar(self, entrada: EntradaEvaluacion) -> EvaluacionCriterios:
        self.entradas.append(entrada)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, BaseException):
            raise respuesta
        return respuesta


def error(tipo=TipoErrorEvaluacion.TIMEOUT, detalle="sin respuesta en 4 s"):
    return ErrorEvaluacion(tipo, detalle)


def entrada(texto="Hay cables expuestos en el pasillo", dependencia="Ingeniería", ubicacion="B"):
    return EntradaEvaluacion(
        texto=texto,
        canal=Canal.FORMULARIO,
        dependencia_informada=dependencia,
        ubicacion_informada=ubicacion,
    )


def reloj_falso(*instantes):
    valores = iter(instantes)
    return lambda: next(valores)


def triar(config, principal, respaldo=None, entrada_=None, reloj=None):
    return triar_pedido(
        entrada_ or entrada(),
        principal,
        respaldo or EvaluadorFalso(nombre="palabras_clave"),
        config,
        reloj=reloj or reloj_falso(10.0, 10.25),
    )


# --- Anonimización ---


@pytest.mark.parametrize(
    "texto",
    [
        "escribir a juan.perez@uni.edu.py por el aula",
        "Contacto: Maria_Lopez+mant@facultad.una.py.",
    ],
)
def test_anonimiza_correos(texto):
    resultado = anonimizar_texto(texto)
    assert "@" not in resultado
    assert "[correo]" in resultado


@pytest.mark.parametrize(
    "telefono", ["0981 123 456", "+595 981 123456", "(021) 555-1234", "0981123456", "4567-8901"]
)
def test_anonimiza_telefonos(telefono):
    resultado = anonimizar_texto(f"Se cayó el techo, llamar al {telefono} urgente")
    assert resultado == "Se cayó el techo, llamar al [telefono] urgente"


@pytest.mark.parametrize(
    "texto",
    [
        "El aula 203 del piso 2 no tiene luz desde 2024",
        "Examen el 12/03/2025 a las 10:30",
        "Faltan 150 sillas en el bloque 3",
    ],
)
def test_no_altera_numeros_que_no_son_telefonos(texto):
    assert anonimizar_texto(texto) == texto


def test_anonimizar_es_idempotente():
    una_vez = anonimizar_texto("mail a@b.com o al 0981 123 456")
    assert anonimizar_texto(una_vez) == una_vez == "mail [correo] o al [telefono]"


def test_construir_entrada_anonimiza_y_no_lleva_contacto():
    construida = construir_entrada(
        "Gotera en el aula 12, avisar a ana@uni.edu.py o al 0981 555 444",
        canal=Canal.TEXTO_LIBRE,
        dependencia="Rectorado",
        ubicacion=None,
    )
    assert construida.texto == "Gotera en el aula 12, avisar a [correo] o al [telefono]"
    assert construida.dependencia_informada == "Rectorado"
    assert construida.ubicacion_informada is None
    assert "contacto" not in construida.model_dump()


def test_construir_entrada_trata_vacios_como_no_informados():
    construida = construir_entrada("Gotera", canal=Canal.FORMULARIO, dependencia="  ", ubicacion="")
    assert construida.dependencia_informada is None
    assert construida.ubicacion_informada is None


def test_triar_anonimiza_la_entrada_antes_de_evaluar(config):
    principal = EvaluadorFalso(evaluacion(config))
    triar(config, principal, entrada_=entrada("Cables expuestos, llamar al 0981 123 456"))
    assert principal.entradas[0].texto == "Cables expuestos, llamar al [telefono]"


# --- Éxito de la IA ---


def test_exito_al_primer_intento(config):
    principal = EvaluadorFalso(evaluacion(config), modelo="gemini-2.5-flash")
    resultado = triar(config, principal)

    assert resultado.origen is OrigenResultado.IA
    assert resultado.modelo == "gemini-2.5-flash"
    assert resultado.intentos_ia == 1
    assert resultado.errores == []
    assert resultado.motivos_revision == []
    assert resultado.evaluacion == evaluacion(config)
    assert resultado.calculo.prioridad_final is Prioridad.P1  # regla de riesgo para personas
    assert resultado.justificacion.es_respaldo is False
    assert "Prioridad P1" in resultado.justificacion.texto
    assert resultado.version_config == config.version
    assert resultado.duracion_ms == 250


def test_exito_tras_el_reintento(config):
    principal = EvaluadorFalso(error(), evaluacion(config))
    respaldo = EvaluadorFalso()
    resultado = triar(config, principal, respaldo)

    assert resultado.origen is OrigenResultado.IA
    assert resultado.intentos_ia == 2
    assert len(resultado.errores) == 1
    assert "timeout" in resultado.errores[0]
    assert respaldo.entradas == []


@pytest.mark.parametrize("tipo", [t for t in TipoErrorEvaluacion if t.name != "NO_CONFIGURADO"])
def test_dos_fallos_pasan_al_respaldo(config, tipo):
    principal = EvaluadorFalso(error(tipo), error(tipo))
    respaldo = EvaluadorFalso(evaluacion(config, confianza=0.0))
    resultado = triar(config, principal, respaldo)

    assert len(principal.entradas) == 2
    assert len(respaldo.entradas) == 1
    assert resultado.origen is OrigenResultado.RESPALDO
    assert resultado.modelo is None
    assert resultado.intentos_ia == 2
    assert len(resultado.errores) == 2
    assert MotivoRevision.CLASIFICACION_RESPALDO in resultado.motivos_revision
    assert resultado.calculo.prioridad_final is Prioridad.P1
    assert resultado.justificacion.texto.startswith(AVISO_RESPALDO)


def test_falta_de_configuracion_pasa_directo_al_respaldo(config):
    principal = EvaluadorFalso(error(TipoErrorEvaluacion.NO_CONFIGURADO, "falta la API key"))
    respaldo = EvaluadorFalso(evaluacion(config, confianza=0.0))
    resultado = triar(config, principal, respaldo)

    assert len(principal.entradas) == 1
    assert resultado.origen is OrigenResultado.RESPALDO
    assert resultado.intentos_ia == 0
    assert resultado.errores == ["principal (falso): no_configurado: falta la API key"]


def test_excepcion_inesperada_del_principal_se_trata_como_falla(config):
    principal = EvaluadorFalso(RuntimeError("explotó"), evaluacion(config))
    resultado = triar(config, principal)
    assert resultado.origen is OrigenResultado.IA
    assert resultado.intentos_ia == 2
    assert "explotó" in resultado.errores[0]


def test_resultado_de_respaldo_no_marca_confianza_baja(config):
    principal = EvaluadorFalso(error(TipoErrorEvaluacion.NO_CONFIGURADO))
    respaldo = EvaluadorFalso(evaluacion(config, confianza=0.0))
    resultado = triar(config, principal, respaldo)
    assert resultado.motivos_revision == [MotivoRevision.CLASIFICACION_RESPALDO]


# --- Sin clasificación ---


def test_respaldo_sin_coincidencias_da_sin_clasificacion(config):
    principal = EvaluadorFalso(error(), error())
    respaldo = EvaluadorFalso(error(TipoErrorEvaluacion.SIN_COINCIDENCIAS, "ningún tipo"))
    resultado = triar(config, principal, respaldo)

    assert resultado.origen is OrigenResultado.SIN_CLASIFICACION
    assert resultado.evaluacion is None
    assert resultado.calculo is None
    assert resultado.justificacion.texto == TEXTO_SIN_CLASIFICACION
    assert resultado.motivos_revision == [MotivoRevision.SIN_CLASIFICACION]
    assert len(resultado.errores) == 3
    assert "sin_coincidencias" in resultado.errores[-1]


def test_excepcion_inesperada_del_respaldo_da_sin_clasificacion(config):
    principal = EvaluadorFalso(error(TipoErrorEvaluacion.NO_CONFIGURADO))
    respaldo = EvaluadorFalso(ValueError("archivo roto"))
    resultado = triar(config, principal, respaldo)
    assert resultado.origen is OrigenResultado.SIN_CLASIFICACION
    assert "archivo roto" in resultado.errores[-1]


def test_sin_clasificacion_marca_dependencia_y_ubicacion_no_informadas(config):
    principal = EvaluadorFalso(error(TipoErrorEvaluacion.NO_CONFIGURADO))
    respaldo = EvaluadorFalso(error(TipoErrorEvaluacion.SIN_COINCIDENCIAS))
    resultado = triar(
        config, principal, respaldo, entrada_=entrada(dependencia=None, ubicacion=None)
    )
    assert resultado.motivos_revision == [
        MotivoRevision.DEPENDENCIA_NO_INFORMADA,
        MotivoRevision.UBICACION_NO_INFORMADA,
        MotivoRevision.SIN_CLASIFICACION,
    ]


def test_evaluacion_incompatible_con_el_motor_no_lanza(config):
    criterios_incompletos = {"riesgo_personas": PuntajeCriterio(puntaje=3, evidencia=["x"])}
    principal = EvaluadorFalso(evaluacion(config, criterios=criterios_incompletos))
    respaldo = EvaluadorFalso(evaluacion(config, confianza=0.0))
    resultado = triar(config, principal, respaldo)

    assert resultado.origen is OrigenResultado.RESPALDO
    assert len(principal.entradas) == 1  # un resultado inválido no se reintenta contra la IA
    assert any("faltan" in e.lower() or "criterio" in e.lower() for e in resultado.errores)


# --- Motivos de revisión ---


def test_confianza_059_requiere_revision(config):
    resultado = triar(config, EvaluadorFalso(evaluacion(config, confianza=0.59)))
    assert resultado.motivos_revision == [MotivoRevision.CONFIANZA_BAJA]


def test_confianza_igual_a_la_minima_no_requiere_revision(config):
    resultado = triar(config, EvaluadorFalso(evaluacion(config, confianza=0.6)))
    assert resultado.motivos_revision == []


def test_texto_insuficiente_y_conflicto_de_tipos(config):
    ev = evaluacion(config, texto_insuficiente=True, conflicto_tipos=True)
    resultado = triar(config, EvaluadorFalso(ev))
    assert resultado.motivos_revision == [
        MotivoRevision.TEXTO_INSUFICIENTE,
        MotivoRevision.CONFLICTO_TIPOS,
    ]


def test_dependencia_y_ubicacion_no_informadas(config):
    ev = evaluacion(config, dependencia=None, ubicacion="  ")
    resultado = triar(
        config, EvaluadorFalso(ev), entrada_=entrada(dependencia=None, ubicacion=None)
    )
    assert resultado.motivos_revision == [
        MotivoRevision.DEPENDENCIA_NO_INFORMADA,
        MotivoRevision.UBICACION_NO_INFORMADA,
    ]


def test_dependencia_informada_o_extraida_no_requiere_revision(config):
    ev = evaluacion(config, dependencia=None, ubicacion="Bloque B")
    resultado = triar(config, EvaluadorFalso(ev), entrada_=entrada(ubicacion=None))
    assert resultado.motivos_revision == []


# --- Garantías ---


def test_la_entrada_enviada_no_contiene_el_contacto(config):
    principal = EvaluadorFalso(error(), error())
    respaldo = EvaluadorFalso(evaluacion(config, confianza=0.0))
    construida = construir_entrada(
        "Pérdida de agua en el baño. Contacto: pedro@uni.edu.py, 0991 222 333",
        canal=Canal.TEXTO_LIBRE,
        dependencia=None,
        ubicacion=None,
    )
    triar(config, principal, respaldo, entrada_=construida)

    for enviada in principal.entradas + respaldo.entradas:
        volcado = str(enviada.model_dump())
        assert "pedro@uni.edu.py" not in volcado
        assert "0991 222 333" not in volcado


def test_nunca_lanza_aunque_falle_la_justificacion(config, monkeypatch):
    def falla(*args, **kwargs):
        raise RuntimeError("plantilla rota")

    monkeypatch.setattr("triage.pipeline.redactar_justificacion", falla)
    resultado = triar(
        config, EvaluadorFalso(evaluacion(config)), EvaluadorFalso(evaluacion(config))
    )
    assert resultado.origen is OrigenResultado.SIN_CLASIFICACION
    assert resultado.justificacion.texto == TEXTO_SIN_CLASIFICACION
    assert any("plantilla rota" in e for e in resultado.errores)


def test_es_deterministico(config):
    primero = triar(config, EvaluadorFalso(evaluacion(config)))
    segundo = triar(config, EvaluadorFalso(evaluacion(config)))
    assert primero == segundo
