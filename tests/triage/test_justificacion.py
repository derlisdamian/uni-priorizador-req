"""Redacción de la justificación en español (`triage.justificacion`)."""

from pathlib import Path

import pytest

from triage.config import ConfiguracionTriage, cargar_configuracion
from triage.justificacion import AVISO_RESPALDO, redactar_justificacion
from triage.schemas import EvaluacionCriterios, OrigenResultado, PuntajeCriterio
from triage.scoring import calcular_prioridad

DIRECTORIO_INICIAL = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def config() -> ConfiguracionTriage:
    return cargar_configuracion(DIRECTORIO_INICIAL)


def evaluacion(config, tipos_secundarios=(), **valores: tuple[int, list[str]]):
    criterios = {
        clave: PuntajeCriterio(puntaje=0, evidencia=[]) for clave in config.claves_criterios()
    }
    for clave, (puntaje, evidencia) in valores.items():
        criterios[clave] = PuntajeCriterio(puntaje=puntaje, evidencia=evidencia)
    return EvaluacionCriterios(
        descripcion_normalizada="Problema reportado",
        dependencia=None,
        ubicacion=None,
        tipo_principal="Electricidad",
        tipos_secundarios=list(tipos_secundarios),
        criterios=criterios,
        confianza=0.9,
        texto_insuficiente=False,
        conflicto_tipos=False,
    )


def redactar(ev, config, origen=OrigenResultado.IA):
    calculo = calcular_prioridad({c: p.puntaje for c, p in ev.criterios.items()}, config)
    return redactar_justificacion(ev, calculo, origen, config)


# --- Sin escalamiento ---


@pytest.fixture
def sin_escalamiento(config):
    # 22×2 + 12×3 + 10×1 + 10×2 = 110 → 36,67 → P3
    return evaluacion(
        config,
        tipos_secundarios=["Infraestructura"],
        riesgo_personas=(2, ["enchufe suelto"]),
        impacto_academico=(3, ["no se puede dar clase", "examen el lunes"]),
        usuarios_afectados=(1, ["un aula"]),
        urgencia_temporal=(2, ["mañana"]),
    )


def test_incluye_prioridad_puntaje_umbral_y_tipos(config, sin_escalamiento):
    texto = redactar(sin_escalamiento, config).texto
    assert texto.startswith("Prioridad P3")
    assert "puntaje total de 36,7 sobre 100" in texto
    assert "corresponde a P3 por umbral" in texto
    assert "Tipo principal: Electricidad" in texto
    assert "Infraestructura" in texto
    assert "No se aplicaron reglas de escalamiento." in texto


def test_lista_los_criterios_con_puntaje_alto_con_nombre_puntaje_y_evidencia(
    config, sin_escalamiento
):
    justificacion = redactar(sin_escalamiento, config)
    assert [c.clave for c in justificacion.criterios_destacados] == [
        "riesgo_personas",
        "impacto_academico",
        "urgencia_temporal",
    ]
    destacado = justificacion.criterios_destacados[1]
    assert destacado.nombre == "Impacto en actividades académicas"
    assert destacado.puntaje == 3
    assert destacado.evidencia == ["no se puede dar clase", "examen el lunes"]
    assert (
        "Impacto en actividades académicas (puntaje 3): «no se puede dar clase», «examen el lunes»"
        in justificacion.texto
    )
    assert "Riesgo para las personas (puntaje 2): «enchufe suelto»" in justificacion.texto


def test_omite_los_criterios_con_puntaje_menor_a_dos(config, sin_escalamiento):
    texto = redactar(sin_escalamiento, config).texto
    assert "Cantidad de usuarios afectados" not in texto
    assert "un aula" not in texto


def test_sin_tipos_secundarios_no_los_menciona(config):
    texto = redactar(evaluacion(config), config).texto
    assert "Tipo principal: Electricidad." in texto
    assert "secundarios" not in texto


def test_sin_criterios_destacados_lo_indica(config):
    justificacion = redactar(evaluacion(config), config)
    assert justificacion.criterios_destacados == []
    assert "Ningún criterio alcanzó un puntaje medio o alto." in justificacion.texto


def test_un_resultado_de_ia_no_es_de_respaldo(config, sin_escalamiento):
    justificacion = redactar(sin_escalamiento, config)
    assert justificacion.es_respaldo is False
    assert AVISO_RESPALDO not in justificacion.texto


# --- Con escalamiento ---


def test_con_escalamiento_explica_umbral_final_y_regla_responsable(config):
    # 22×3 = 66 → 22,00 → P3 por umbral, escalado a P1
    ev = evaluacion(config, riesgo_personas=(3, ["cables pelados en el pasillo"]))
    texto = redactar(ev, config).texto
    assert texto.startswith("Prioridad P1")
    assert "puntaje total de 22,0 sobre 100" in texto
    assert "Por umbral correspondía P3" in texto
    assert "se elevó a P1 por la regla «Riesgo para las personas grave (puntaje 3)»" in texto
    assert "«cables pelados en el pasillo»" in texto


def test_menciona_las_reglas_cumplidas_que_no_cambiaron_la_prioridad(config):
    ev = evaluacion(
        config,
        riesgo_personas=(3, ["cables pelados"]),
        accesibilidad=(3, ["único ascensor"]),
    )
    texto = redactar(ev, config).texto
    assert "se elevó a P1 por la regla «Riesgo para las personas grave (puntaje 3)»" in texto
    assert "También se cumplió la regla «Accesibilidad sin alternativa (puntaje 3)»" in texto


def test_regla_cumplida_sin_cambio_cuando_el_umbral_ya_alcanzaba(config):
    # 10×3 + 12×3 + 10×3 + 10×3 + 10×2 = 146 → 48,67 → P2; la regla de accesibilidad exige P2
    ev = evaluacion(
        config,
        accesibilidad=(3, ["único ascensor"]),
        impacto_academico=(3, ["examen"]),
        urgencia_temporal=(3, ["mañana"]),
        deterioro_progresivo=(3, ["filtración"]),
        usuarios_afectados=(2, ["todo el piso"]),
    )
    texto = redactar(ev, config).texto
    assert "corresponde a P2 por umbral" in texto
    assert "se elevó" not in texto
    assert (
        "Se cumplió la regla «Accesibilidad sin alternativa (puntaje 3)», "
        "pero la prioridad por umbral ya era igual o más urgente."
    ) in texto


# --- Respaldo ---


def test_un_resultado_de_respaldo_empieza_con_el_aviso(config, sin_escalamiento):
    justificacion = redactar(sin_escalamiento, config, OrigenResultado.RESPALDO)
    assert justificacion.es_respaldo is True
    assert justificacion.texto.startswith(
        "Clasificación de respaldo por palabras clave (sin IA); requiere revisión. Prioridad P3"
    )
    assert (
        AVISO_RESPALDO
        == "Clasificación de respaldo por palabras clave (sin IA); requiere revisión."
    )


# --- Sin clasificación ---


def test_sin_clasificacion_genera_un_texto_especifico(config):
    justificacion = redactar_justificacion(None, None, OrigenResultado.SIN_CLASIFICACION, config)
    assert justificacion.criterios_destacados == []
    assert justificacion.es_respaldo is False
    assert justificacion.texto.startswith("No se pudo clasificar el pedido")
    assert "Prioridad" not in justificacion.texto
    assert "asignar la prioridad y el tipo" in justificacion.texto


@pytest.mark.parametrize("origen", [OrigenResultado.IA, OrigenResultado.RESPALDO])
def test_un_resultado_clasificado_exige_evaluacion_y_calculo(config, origen):
    with pytest.raises(ValueError):
        redactar_justificacion(None, None, origen, config)


# --- Determinismo ---


def test_la_justificacion_es_determinista(config, sin_escalamiento):
    assert redactar(sin_escalamiento, config) == redactar(sin_escalamiento, config)
