"""Contratos de dominio: enums y schemas Pydantic de `triage.schemas`."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from triage.schemas import (
    CalculoPrioridad,
    Canal,
    CriterioJustificado,
    EntradaEvaluacion,
    EvaluacionCriterios,
    Justificacion,
    MotivoRevision,
    OrigenResultado,
    Prioridad,
    PuntajeCriterio,
    ReglaAplicada,
    ResultadoTriage,
)


def evaluacion(**cambios) -> EvaluacionCriterios:
    datos = {
        "descripcion_normalizada": "Pérdida de agua en el baño del primer piso",
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Baño del primer piso",
        "tipo_principal": "sanitaria",
        "tipos_secundarios": [],
        "criterios": {
            "seguridad": PuntajeCriterio(puntaje=0, evidencia=[]),
            "continuidad": PuntajeCriterio(puntaje=2, evidencia=["pérdida de agua"]),
        },
        "confianza": 0.85,
        "texto_insuficiente": False,
        "conflicto_tipos": False,
    }
    return EvaluacionCriterios(**(datos | cambios))


def calculo(**cambios) -> CalculoPrioridad:
    datos = {
        "suma_ponderada_x3": 140,
        "puntaje_total": Decimal("46.67"),
        "prioridad_umbral": Prioridad.P2,
        "prioridad_final": Prioridad.P2,
        "reglas_aplicadas": [],
    }
    return CalculoPrioridad(**(datos | cambios))


def justificacion(es_respaldo: bool = False) -> Justificacion:
    return Justificacion(texto="Prioridad P2.", criterios_destacados=[], es_respaldo=es_respaldo)


def resultado(**cambios) -> ResultadoTriage:
    datos = {
        "origen": OrigenResultado.IA,
        "modelo": "gemini-2.5-flash",
        "evaluacion": evaluacion(),
        "calculo": calculo(),
        "justificacion": justificacion(),
        "motivos_revision": [],
        "intentos_ia": 1,
        "errores": [],
        "version_config": "a1b2c3d4e5f6",
        "duracion_ms": 1200,
    }
    return ResultadoTriage(**(datos | cambios))


# --- Enums ---


def test_el_orden_natural_de_la_prioridad_coincide_con_la_urgencia():
    assert Prioridad.P1 < Prioridad.P2 < Prioridad.P3 < Prioridad.P4
    assert min(Prioridad.P3, Prioridad.P1, Prioridad.P4) is Prioridad.P1
    assert sorted([Prioridad.P4, Prioridad.P2, Prioridad.P1]) == [
        Prioridad.P1,
        Prioridad.P2,
        Prioridad.P4,
    ]


def test_hay_exactamente_cuatro_prioridades():
    assert [p.name for p in Prioridad] == ["P1", "P2", "P3", "P4"]
    assert [p.value for p in Prioridad] == [1, 2, 3, 4]


def test_valores_de_canal_y_origen():
    assert {c.value for c in Canal} == {"formulario", "texto_libre"}
    assert {o.value for o in OrigenResultado} == {"ia", "respaldo", "sin_clasificacion"}


def test_valores_de_motivos_de_revision():
    assert {m.value for m in MotivoRevision} == {
        "confianza_baja",
        "texto_insuficiente",
        "conflicto_tipos",
        "dependencia_no_informada",
        "ubicacion_no_informada",
        "clasificacion_respaldo",
        "sin_clasificacion",
    }


def test_los_enums_de_texto_se_comparan_con_su_valor():
    assert Canal.TEXTO_LIBRE == "texto_libre"
    assert MotivoRevision("confianza_baja") is MotivoRevision.CONFIANZA_BAJA


# --- EntradaEvaluacion ---


def test_entrada_de_evaluacion_no_tiene_campos_de_contacto():
    campos = set(EntradaEvaluacion.model_fields)
    assert campos == {"texto", "canal", "dependencia_informada", "ubicacion_informada"}
    assert not any("contacto" in campo for campo in campos)


def test_entrada_de_evaluacion_rechaza_campos_extra_como_el_contacto():
    with pytest.raises(ValidationError):
        EntradaEvaluacion(
            texto="Se rompió la canilla",
            canal=Canal.FORMULARIO,
            dependencia_informada=None,
            ubicacion_informada=None,
            contacto="ana@uni.edu",
        )


def test_entrada_de_evaluacion_admite_dependencia_y_ubicacion_ausentes():
    entrada = EntradaEvaluacion(
        texto="Se rompió la canilla",
        canal="texto_libre",
        dependencia_informada=None,
        ubicacion_informada=None,
    )
    assert entrada.canal is Canal.TEXTO_LIBRE
    assert "contacto" not in entrada.model_dump_json()


# --- PuntajeCriterio y EvaluacionCriterios ---


@pytest.mark.parametrize("puntaje", [0, 1, 2, 3])
def test_puntaje_en_rango(puntaje):
    assert PuntajeCriterio(puntaje=puntaje, evidencia=[]).puntaje == puntaje


@pytest.mark.parametrize("puntaje", [-1, 4, 10])
def test_puntaje_fuera_de_rango_se_rechaza(puntaje):
    with pytest.raises(ValidationError):
        PuntajeCriterio(puntaje=puntaje, evidencia=[])


@pytest.mark.parametrize("puntaje", [1.5, 2.0, "2", True])
def test_puntaje_no_entero_se_rechaza(puntaje):
    with pytest.raises(ValidationError):
        PuntajeCriterio(puntaje=puntaje, evidencia=[])


def test_evidencia_admite_hasta_tres_fragmentos():
    assert len(PuntajeCriterio(puntaje=2, evidencia=["a", "b", "c"]).evidencia) == 3
    with pytest.raises(ValidationError):
        PuntajeCriterio(puntaje=2, evidencia=["a", "b", "c", "d"])


@pytest.mark.parametrize("confianza", [0.0, 0.59, 1.0])
def test_confianza_en_rango(confianza):
    assert evaluacion(confianza=confianza).confianza == confianza


@pytest.mark.parametrize("confianza", [-0.01, 1.01, float("nan"), float("inf")])
def test_confianza_fuera_de_rango_se_rechaza(confianza):
    with pytest.raises(ValidationError):
        evaluacion(confianza=confianza)


def test_evaluacion_valida_los_puntajes_anidados():
    with pytest.raises(ValidationError):
        criterios = {"seguridad": {"puntaje": 5, "evidencia": []}}
        EvaluacionCriterios.model_validate(evaluacion().model_dump() | {"criterios": criterios})


def test_evaluacion_conserva_banderas_y_campos_extraidos():
    ev = evaluacion(texto_insuficiente=True, conflicto_tipos=True, dependencia=None)
    assert ev.texto_insuficiente is True
    assert ev.conflicto_tipos is True
    assert ev.dependencia is None
    assert ev.ubicacion == "Baño del primer piso"


def test_evaluacion_se_serializa_y_reconstruye_desde_json():
    ev = evaluacion()
    assert EvaluacionCriterios.model_validate_json(ev.model_dump_json()) == ev


# --- CalculoPrioridad ---


def test_calculo_con_escalamiento_eleva_la_prioridad():
    regla = ReglaAplicada(
        id="riesgo_alto", descripcion="Seguridad = 3", prioridad_minima=Prioridad.P1
    )
    c = calculo(prioridad_final=Prioridad.P1, reglas_aplicadas=[regla])
    assert c.prioridad_final is Prioridad.P1
    assert c.reglas_aplicadas[0].prioridad_minima is Prioridad.P1


def test_calculo_rechaza_una_prioridad_final_menos_urgente_que_la_del_umbral():
    with pytest.raises(ValidationError):
        calculo(prioridad_umbral=Prioridad.P2, prioridad_final=Prioridad.P3)


@pytest.mark.parametrize("suma", [-1, 301])
def test_calculo_rechaza_suma_ponderada_fuera_de_rango(suma):
    with pytest.raises(ValidationError):
        calculo(suma_ponderada_x3=suma)


@pytest.mark.parametrize("total", [Decimal("-0.01"), Decimal("100.01")])
def test_calculo_rechaza_puntaje_total_fuera_de_rango(total):
    with pytest.raises(ValidationError):
        calculo(puntaje_total=total)


def test_calculo_rechaza_puntaje_total_con_mas_de_dos_decimales():
    with pytest.raises(ValidationError):
        calculo(puntaje_total=Decimal("46.667"))


# --- Justificación ---


def test_criterio_justificado_valida_el_puntaje():
    with pytest.raises(ValidationError):
        CriterioJustificado(clave="seguridad", nombre="Seguridad", puntaje=4, evidencia=[])


# --- ResultadoTriage ---


def test_resultado_de_ia_completo():
    r = resultado()
    assert r.origen is OrigenResultado.IA
    assert r.calculo.prioridad_final is Prioridad.P2
    assert r.version_config == "a1b2c3d4e5f6"


def test_resultado_sin_clasificacion_no_tiene_evaluacion_ni_calculo():
    r = resultado(
        origen=OrigenResultado.SIN_CLASIFICACION,
        modelo=None,
        evaluacion=None,
        calculo=None,
        motivos_revision=[MotivoRevision.SIN_CLASIFICACION],
        intentos_ia=2,
        errores=["timeout", "timeout", "sin_coincidencias"],
    )
    assert r.evaluacion is None and r.calculo is None


@pytest.mark.parametrize(
    "cambios",
    [
        {"origen": OrigenResultado.SIN_CLASIFICACION},
        {"origen": OrigenResultado.SIN_CLASIFICACION, "evaluacion": None},
        {"origen": OrigenResultado.IA, "evaluacion": None, "calculo": None},
        {"origen": OrigenResultado.IA, "calculo": None},
    ],
)
def test_resultado_rechaza_combinaciones_inconsistentes_de_origen(cambios):
    with pytest.raises(ValidationError):
        resultado(**cambios)


def test_resultado_de_respaldo_requiere_el_motivo_de_clasificacion_de_respaldo():
    with pytest.raises(ValidationError):
        resultado(origen=OrigenResultado.RESPALDO, modelo=None, motivos_revision=[])
    r = resultado(
        origen=OrigenResultado.RESPALDO,
        modelo=None,
        justificacion=justificacion(es_respaldo=True),
        motivos_revision=[MotivoRevision.CLASIFICACION_RESPALDO],
    )
    assert MotivoRevision.CLASIFICACION_RESPALDO in r.motivos_revision


@pytest.mark.parametrize("intentos", [-1, 3])
def test_resultado_rechaza_intentos_fuera_de_rango(intentos):
    with pytest.raises(ValidationError):
        resultado(intentos_ia=intentos)


def test_resultado_rechaza_duracion_negativa():
    with pytest.raises(ValidationError):
        resultado(duracion_ms=-1)


def test_resultado_se_serializa_y_reconstruye_desde_json():
    r = resultado()
    assert ResultadoTriage.model_validate_json(r.model_dump_json()) == r


def test_regla_aplicada_no_produjo_cambio_por_defecto():
    regla = ReglaAplicada(id="r", descripcion="Regla", prioridad_minima=Prioridad.P2)
    assert regla.produjo_cambio is False
