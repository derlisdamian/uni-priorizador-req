"""Validación de las evaluaciones recibidas (`triage.validacion`)."""

from pathlib import Path

import pytest

from triage.config import ConfiguracionTriage, cargar_configuracion
from triage.schemas import EvaluacionCriterios, PuntajeCriterio
from triage.texto import normalizar_texto
from triage.validacion import EvaluacionInvalida, validar_evaluacion

DIRECTORIO_INICIAL = Path(__file__).resolve().parents[2] / "config"

TEXTO = (
    "Hay cables pelados en el pasillo del 2º piso del Pabellón Central y una filtración "
    "sobre el tablero. Mañana   hay examen en el aula 12."
)


@pytest.fixture(scope="module")
def config() -> ConfiguracionTriage:
    return cargar_configuracion(DIRECTORIO_INICIAL)


def candidata(config: ConfiguracionTriage, criterios: dict | None = None, **cambios):
    base = {clave: PuntajeCriterio(puntaje=0, evidencia=[]) for clave in config.claves_criterios()}
    base |= {
        "riesgo_personas": PuntajeCriterio(puntaje=3, evidencia=["cables pelados en el pasillo"]),
        "deterioro_progresivo": PuntajeCriterio(
            puntaje=2, evidencia=["filtración sobre el tablero"]
        ),
    }
    datos = {
        "descripcion_normalizada": "Cables pelados y filtración sobre el tablero eléctrico",
        "dependencia": None,
        "ubicacion": "Pasillo del 2º piso, Pabellón Central",
        "tipo_principal": "Electricidad",
        "tipos_secundarios": ["Cubierta"],
        "criterios": base | (criterios or {}),
        "confianza": 0.9,
        "texto_insuficiente": False,
        "conflicto_tipos": False,
    }
    return EvaluacionCriterios(**(datos | cambios))


def motivos_de_rechazo(evaluacion, config, texto=TEXTO) -> list[str]:
    with pytest.raises(EvaluacionInvalida) as excinfo:
        validar_evaluacion(evaluacion, texto, config)
    assert excinfo.value.motivos
    return excinfo.value.motivos


# --- Normalización ---


def test_normalizar_quita_mayusculas_acentos_y_espacios_repetidos():
    assert normalizar_texto("  Filtración  SOBRE\tel\n tablero  ") == "filtracion sobre el tablero"


def test_normalizar_conserva_la_enie_como_n():
    assert normalizar_texto("Mañana") == "manana"


# --- Evaluación válida ---


def test_una_evaluacion_valida_se_devuelve_con_su_evidencia(config):
    original = candidata(config)
    validada = validar_evaluacion(original, TEXTO, config)
    assert validada == original
    assert validada is not original


@pytest.mark.parametrize(
    "fragmento",
    ["CABLES PELADOS en el pasillo", "filtracion sobre el tablero", "mañana hay examen"],
)
def test_la_evidencia_se_compara_sin_mayusculas_acentos_ni_espacios(config, fragmento):
    evaluacion = candidata(
        config, {"impacto_academico": PuntajeCriterio(puntaje=3, evidencia=[fragmento])}
    )
    validada = validar_evaluacion(evaluacion, TEXTO, config)
    assert validada.criterios["impacto_academico"].evidencia == [fragmento]


def test_la_evidencia_parafraseada_se_descarta(config):
    evaluacion = candidata(
        config,
        {
            "impacto_academico": PuntajeCriterio(
                puntaje=3, evidencia=["hay examen en el aula 12", "se suspenden los exámenes"]
            ),
            "urgencia_temporal": PuntajeCriterio(
                puntaje=1, evidencia=["es para la semana próxima"]
            ),
        },
    )
    validada = validar_evaluacion(evaluacion, TEXTO, config)
    assert validada.criterios["impacto_academico"].evidencia == ["hay examen en el aula 12"]
    assert validada.criterios["urgencia_temporal"].evidencia == []


def test_la_evidencia_vacia_se_descarta(config):
    evaluacion = candidata(
        config, {"urgencia_temporal": PuntajeCriterio(puntaje=1, evidencia=["   ", ""])}
    )
    validada = validar_evaluacion(evaluacion, TEXTO, config)
    assert validada.criterios["urgencia_temporal"].evidencia == []


def test_no_modifica_la_evaluacion_recibida(config):
    evaluacion = candidata(
        config, {"urgencia_temporal": PuntajeCriterio(puntaje=1, evidencia=["inventado"])}
    )
    validar_evaluacion(evaluacion, TEXTO, config)
    assert evaluacion.criterios["urgencia_temporal"].evidencia == ["inventado"]


# --- Tipos ---


def test_rechaza_un_tipo_principal_fuera_de_la_lista(config):
    motivos = motivos_de_rechazo(candidata(config, tipo_principal="Jardinería"), config)
    assert any("Jardinería" in m for m in motivos)


def test_rechaza_un_tipo_secundario_fuera_de_la_lista(config):
    motivos = motivos_de_rechazo(
        candidata(config, tipos_secundarios=["Cubierta", "Pintura"]), config
    )
    assert any("Pintura" in m for m in motivos)


def test_rechaza_el_tipo_principal_repetido_entre_los_secundarios(config):
    motivos = motivos_de_rechazo(
        candidata(config, tipos_secundarios=["Electricidad", "Cubierta"]), config
    )
    assert any("Electricidad" in m for m in motivos)


# --- Criterios y puntajes ---


def test_rechaza_un_criterio_faltante(config):
    evaluacion = candidata(config)
    criterios = dict(evaluacion.criterios)
    del criterios["seguridad"]
    motivos = motivos_de_rechazo(evaluacion.model_copy(update={"criterios": criterios}), config)
    assert any("seguridad" in m for m in motivos)


def test_rechaza_un_criterio_desconocido(config):
    evaluacion = candidata(config, {"belleza": PuntajeCriterio(puntaje=1, evidencia=[])})
    motivos = motivos_de_rechazo(evaluacion, config)
    assert any("belleza" in m for m in motivos)


@pytest.mark.parametrize("puntaje", [4, -1, 2.5, True])
def test_rechaza_un_puntaje_fuera_de_rango_o_no_entero(config, puntaje):
    # model_construct simula una respuesta que no pasó por la validación de Pydantic.
    fuera_de_rango = PuntajeCriterio.model_construct(puntaje=puntaje, evidencia=["examen"])
    motivos = motivos_de_rechazo(candidata(config, {"impacto_academico": fuera_de_rango}), config)
    assert any("impacto_academico" in m for m in motivos)


# --- Evidencia obligatoria ---


@pytest.mark.parametrize("puntaje", [2, 3])
def test_rechaza_un_criterio_con_puntaje_alto_sin_evidencia(config, puntaje):
    evaluacion = candidata(config, {"seguridad": PuntajeCriterio(puntaje=puntaje, evidencia=[])})
    motivos = motivos_de_rechazo(evaluacion, config)
    assert any("seguridad" in m for m in motivos)


def test_rechaza_un_criterio_con_puntaje_alto_cuya_evidencia_no_aparece_en_el_texto(config):
    evaluacion = candidata(
        config,
        {
            "seguridad": PuntajeCriterio(
                puntaje=3, evidencia=["la salida de emergencia está trabada"]
            )
        },
    )
    motivos = motivos_de_rechazo(evaluacion, config)
    assert any("seguridad" in m for m in motivos)


def test_acepta_un_criterio_con_puntaje_bajo_sin_evidencia(config):
    evaluacion = candidata(config, {"seguridad": PuntajeCriterio(puntaje=1, evidencia=[])})
    assert validar_evaluacion(evaluacion, TEXTO, config).criterios["seguridad"].puntaje == 1


# --- Descripción ---


@pytest.mark.parametrize("descripcion", ["", "   \n"])
def test_rechaza_la_descripcion_normalizada_vacia(config, descripcion):
    motivos = motivos_de_rechazo(candidata(config, descripcion_normalizada=descripcion), config)
    assert any("descripción" in m for m in motivos)


def test_enumera_todos_los_motivos_de_rechazo(config):
    evaluacion = candidata(
        config,
        {"seguridad": PuntajeCriterio(puntaje=3, evidencia=[])},
        tipo_principal="Jardinería",
        descripcion_normalizada="",
    )
    motivos = motivos_de_rechazo(evaluacion, config)
    assert len(motivos) == 3
