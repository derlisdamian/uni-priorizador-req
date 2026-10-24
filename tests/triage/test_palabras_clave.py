"""Evaluador de respaldo por palabras clave (`triage.evaluadores.palabras_clave`)."""

from pathlib import Path

import pytest

from triage.config import (
    ConfiguracionTriage,
    DefinicionCriterio,
    DefinicionTipo,
    SenalRespaldo,
    Umbral,
    cargar_configuracion,
)
from triage.evaluadores import ErrorEvaluacion, EvaluadorPedidos, TipoErrorEvaluacion
from triage.evaluadores.palabras_clave import EvaluadorPalabrasClave
from triage.schemas import Canal, EntradaEvaluacion, Prioridad

DIRECTORIO_INICIAL = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def evaluador() -> EvaluadorPalabrasClave:
    return EvaluadorPalabrasClave(cargar_configuracion(DIRECTORIO_INICIAL))


def entrada(texto: str, dependencia: str | None = None, ubicacion: str | None = None):
    return EntradaEvaluacion(
        texto=texto,
        canal=Canal.TEXTO_LIBRE,
        dependencia_informada=dependencia,
        ubicacion_informada=ubicacion,
    )


def test_cumple_el_puerto_de_evaluadores(evaluador):
    assert isinstance(evaluador, EvaluadorPedidos)
    assert evaluador.nombre == "palabras_clave"


# --- Tipos ---


def test_detecta_el_tipo_con_mas_senales_y_los_demas_como_secundarios(evaluador):
    ev = evaluador.evaluar(
        entrada("Saltó el tablero, hay un enchufe quemado y cables sueltos junto a las puertas.")
    )
    assert ev.tipo_principal == "Electricidad"
    assert ev.tipos_secundarios == ["Infraestructura"]
    assert ev.conflicto_tipos is False


def test_las_senales_se_buscan_sin_mayusculas_ni_acentos(evaluador):
    ev = evaluador.evaluar(entrada("El AIRE ACONDICIONADO y la CALEFACCION no andan"))
    assert ev.tipo_principal == "Climatización"


def test_las_senales_coinciden_con_palabras_completas(evaluador):
    # «red» no debe detectarse dentro de «pared»: solo hay señales de Infraestructura.
    ev = evaluador.evaluar(entrada("Se descascara la pared del aula y hay grietas"))
    assert ev.tipo_principal == "Infraestructura"
    assert ev.tipos_secundarios == []


def test_un_empate_se_resuelve_por_el_orden_de_la_configuracion_y_marca_conflicto(evaluador):
    # Una señal de Sanitaria (cañería) y una de Cubierta (techo): gana la primera en el YAML.
    ev = evaluador.evaluar(entrada("Se rompió una cañería que pasa por el techo"))
    assert ev.tipo_principal == "Sanitaria"
    assert ev.tipos_secundarios == ["Cubierta"]
    assert ev.conflicto_tipos is True


# --- Criterios ---


def test_puntua_los_criterios_con_las_frases_de_respaldo_y_las_usa_como_evidencia(evaluador):
    ev = evaluador.evaluar(
        entrada("Hay cables pelados en el pasillo y mañana hay examen en el aula 3")
    )
    assert ev.criterios["riesgo_personas"].puntaje == 3
    assert ev.criterios["riesgo_personas"].evidencia == ["cables pelados"]
    assert ev.criterios["impacto_academico"].puntaje == 3
    assert ev.criterios["impacto_academico"].evidencia == ["examen"]
    assert ev.criterios["urgencia_temporal"].puntaje == 2
    assert ev.criterios["urgencia_temporal"].evidencia == ["mañana"]


def test_toma_el_mayor_puntaje_de_las_frases_encontradas_en_cada_criterio(evaluador):
    ev = evaluador.evaluar(entrada("El ascensor no anda y es el único ascensor del edificio"))
    assert ev.criterios["accesibilidad"].puntaje == 3
    assert ev.criterios["accesibilidad"].evidencia == ["único ascensor"]


def test_los_criterios_sin_senales_reciben_cero_sin_evidencia(evaluador):
    ev = evaluador.evaluar(entrada("Hay una gotera en el techo"))
    assert set(ev.criterios) == set(evaluador.config.claves_criterios())
    assert ev.criterios["seguridad"].puntaje == 0
    assert ev.criterios["seguridad"].evidencia == []
    assert ev.criterios["costo_estimado"].puntaje == 0


def test_la_evidencia_tiene_como_maximo_tres_frases():
    criterios = [
        DefinicionCriterio(
            clave="riesgo",
            nombre="Riesgo",
            peso=100,
            senales_respaldo=[SenalRespaldo(frase=f, puntaje=2) for f in "abcd"],
        )
    ]
    config = ConfiguracionTriage(
        criterios=criterios,
        umbrales=[
            Umbral(prioridad=Prioridad.P1, minimo=70),
            Umbral(prioridad=Prioridad.P2, minimo=45),
            Umbral(prioridad=Prioridad.P3, minimo=20),
        ],
        reglas=[],
        confianza_minima=0.6,
        tipos=[DefinicionTipo(nombre="General", senales=["a"])],
        version="test",
    )
    ev = EvaluadorPalabrasClave(config).evaluar(entrada("a b c d"))
    assert ev.criterios["riesgo"].evidencia == ["a", "b", "c"]


# --- Otros campos ---


def test_confianza_cero_y_datos_informados(evaluador):
    ev = evaluador.evaluar(
        entrada("Pérdida de agua en el baño", dependencia="Rectorado", ubicacion="Planta baja")
    )
    assert ev.confianza == 0.0
    assert ev.dependencia == "Rectorado"
    assert ev.ubicacion == "Planta baja"
    assert ev.texto_insuficiente is False


def test_la_descripcion_es_el_texto_recortado_a_200_caracteres(evaluador):
    texto = "  Pérdida de agua   en el baño. " + "x" * 300
    ev = evaluador.evaluar(entrada(texto))
    assert ev.descripcion_normalizada.startswith("Pérdida de agua en el baño.")
    assert len(ev.descripcion_normalizada) == 200


# --- Sin coincidencias ---


def test_sin_ningun_tipo_detectado_informa_sin_coincidencias(evaluador):
    with pytest.raises(ErrorEvaluacion) as excinfo:
        evaluador.evaluar(entrada("Necesito que alguien venga a ver esto, gracias"))
    assert excinfo.value.tipo is TipoErrorEvaluacion.SIN_COINCIDENCIAS
    assert excinfo.value.detalle


def test_el_evaluador_es_deterministico(evaluador):
    texto = entrada("Hay cables pelados en el pasillo junto al tablero")
    assert evaluador.evaluar(texto) == evaluador.evaluar(texto)
