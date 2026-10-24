"""Motor de reglas de puntaje y prioridad (`triage.scoring`)."""

import itertools
from decimal import Decimal
from pathlib import Path

import pytest

from triage.config import (
    ConfiguracionTriage,
    DefinicionCriterio,
    DefinicionTipo,
    Umbral,
    cargar_configuracion,
)
from triage.schemas import Prioridad
from triage.scoring import calcular_prioridad

DIRECTORIO_INICIAL = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def config() -> ConfiguracionTriage:
    return cargar_configuracion(DIRECTORIO_INICIAL)


def puntajes(config: ConfiguracionTriage, **valores: int) -> dict[str, int]:
    """Todos los criterios en 0, salvo los indicados."""
    return {clave: 0 for clave in config.claves_criterios()} | valores


def ids_reglas(calculo) -> list[str]:
    return [r.id for r in calculo.reglas_aplicadas]


# --- Puntaje total y umbrales ---


def test_todos_los_criterios_en_cero_dan_puntaje_cero_y_p4(config):
    calculo = calcular_prioridad(puntajes(config), config)
    assert calculo.suma_ponderada_x3 == 0
    assert calculo.puntaje_total == Decimal("0.00")
    assert calculo.prioridad_umbral is Prioridad.P4
    assert calculo.prioridad_final is Prioridad.P4
    assert calculo.reglas_aplicadas == []


def test_todos_los_criterios_en_tres_dan_puntaje_cien_y_p1(config):
    todos = {clave: 3 for clave in config.claves_criterios()}
    calculo = calcular_prioridad(todos, config)
    assert calculo.suma_ponderada_x3 == 300
    assert calculo.puntaje_total == Decimal("100.00")
    assert calculo.prioridad_umbral is Prioridad.P1


def test_el_puntaje_total_es_la_suma_ponderada_dividida_por_tres(config):
    # 22×2 + 12×1 + 10×2 = 76 → 76 / 3 = 25,33
    calculo = calcular_prioridad(
        puntajes(config, riesgo_personas=2, impacto_academico=1, urgencia_temporal=2), config
    )
    assert calculo.suma_ponderada_x3 == 76
    assert calculo.puntaje_total == Decimal("25.33")
    assert calculo.prioridad_umbral is Prioridad.P3


@pytest.fixture(scope="module")
def config_pesos_impares() -> ConfiguracionTriage:
    """Pesos impares para alcanzar los bordes que la configuración inicial (pares) no permite."""
    criterios = [
        DefinicionCriterio(clave=clave, nombre=clave.upper(), peso=peso)
        for clave, peso in (("a", 45), ("b", 35), ("c", 19), ("d", 1))
    ]
    return ConfiguracionTriage(
        criterios=criterios,
        umbrales=[
            Umbral(prioridad=Prioridad.P1, minimo=70),
            Umbral(prioridad=Prioridad.P2, minimo=45),
            Umbral(prioridad=Prioridad.P3, minimo=20),
        ],
        reglas=[],
        confianza_minima=0.6,
        tipos=[DefinicionTipo(nombre="General")],
        version="test",
    )


@pytest.mark.parametrize(
    ("valores", "suma", "total", "prioridad"),
    [
        ((1, 3, 3, 2), 209, "69.67", Prioridad.P2),
        ((1, 3, 3, 3), 210, "70.00", Prioridad.P1),
        ((1, 2, 1, 0), 134, "44.67", Prioridad.P3),
        ((1, 2, 1, 1), 135, "45.00", Prioridad.P2),
        ((0, 0, 3, 2), 59, "19.67", Prioridad.P4),
        ((0, 0, 3, 3), 60, "20.00", Prioridad.P3),
    ],
)
def test_bordes_de_los_umbrales_son_exactos(config_pesos_impares, valores, suma, total, prioridad):
    calculo = calcular_prioridad(dict(zip("abcd", valores, strict=True)), config_pesos_impares)
    assert calculo.suma_ponderada_x3 == suma
    assert calculo.puntaje_total == Decimal(total)
    assert calculo.prioridad_umbral is prioridad
    assert calculo.prioridad_final is prioridad


# --- Reglas de escalamiento ---


@pytest.mark.parametrize(
    ("valores", "regla", "umbral", "final"),
    [
        ({"riesgo_personas": 3}, "riesgo_personas_grave", Prioridad.P3, Prioridad.P1),
        ({"seguridad": 3}, "seguridad_grave", Prioridad.P4, Prioridad.P1),
        ({"accesibilidad": 3}, "accesibilidad_grave", Prioridad.P4, Prioridad.P2),
        (
            {"interrupcion_servicios": 3, "usuarios_afectados": 2},
            "interrupcion_masiva",
            Prioridad.P4,
            Prioridad.P2,
        ),
        (
            {"interrupcion_servicios": 3, "usuarios_afectados": 3},
            "interrupcion_masiva",
            Prioridad.P3,
            Prioridad.P2,
        ),
    ],
)
def test_cada_regla_eleva_la_prioridad_e_informa_que_produjo_el_cambio(
    config, valores, regla, umbral, final
):
    calculo = calcular_prioridad(puntajes(config, **valores), config)
    assert calculo.prioridad_umbral is umbral
    assert calculo.prioridad_final is final
    assert ids_reglas(calculo) == [regla]
    assert calculo.reglas_aplicadas[0].produjo_cambio is True
    assert calculo.reglas_aplicadas[0].prioridad_minima is final


@pytest.mark.parametrize(
    "valores",
    [
        {"riesgo_personas": 2},
        {"seguridad": 2},
        {"accesibilidad": 2},
        {"interrupcion_servicios": 3, "usuarios_afectados": 1},
        {"interrupcion_servicios": 2, "usuarios_afectados": 3},
    ],
)
def test_las_reglas_no_se_aplican_si_no_se_cumplen_todas_sus_condiciones(config, valores):
    calculo = calcular_prioridad(puntajes(config, **valores), config)
    assert calculo.reglas_aplicadas == []
    assert calculo.prioridad_final is calculo.prioridad_umbral


def test_una_regla_nunca_baja_la_prioridad_obtenida_por_umbral(config):
    # Puntaje por umbral P1; la regla de accesibilidad solo exige P2.
    todos = {clave: 3 for clave in config.claves_criterios()} | {"riesgo_personas": 2}
    calculo = calcular_prioridad(todos, config)
    assert calculo.prioridad_umbral is Prioridad.P1
    assert calculo.prioridad_final is Prioridad.P1
    assert "accesibilidad_grave" in ids_reglas(calculo)
    assert all(not r.produjo_cambio for r in calculo.reglas_aplicadas)


def test_regla_cumplida_sin_efecto_se_informa_sin_marcar_el_cambio(config):
    # Por umbral P2 (accesibilidad 3 + otros) y la regla de accesibilidad exige P2.
    calculo = calcular_prioridad(
        puntajes(
            config,
            accesibilidad=3,
            impacto_academico=3,
            urgencia_temporal=3,
            deterioro_progresivo=3,
            usuarios_afectados=2,
        ),
        config,
    )
    assert calculo.prioridad_umbral is Prioridad.P2
    assert calculo.prioridad_final is Prioridad.P2
    assert ids_reglas(calculo) == ["accesibilidad_grave"]
    assert calculo.reglas_aplicadas[0].produjo_cambio is False


def test_las_reglas_se_informan_en_el_orden_de_la_configuracion(config):
    calculo = calcular_prioridad(
        puntajes(
            config,
            accesibilidad=3,
            interrupcion_servicios=3,
            usuarios_afectados=2,
            seguridad=3,
            riesgo_personas=3,
        ),
        config,
    )
    assert ids_reglas(calculo) == [
        "riesgo_personas_grave",
        "seguridad_grave",
        "accesibilidad_grave",
        "interrupcion_masiva",
    ]
    assert calculo.prioridad_final is Prioridad.P1


def test_solo_la_primera_regla_que_alcanza_la_prioridad_final_figura_como_responsable(config):
    calculo = calcular_prioridad(
        puntajes(config, accesibilidad=3, seguridad=3, riesgo_personas=3), config
    )
    cambios = {r.id: r.produjo_cambio for r in calculo.reglas_aplicadas}
    assert cambios == {
        "riesgo_personas_grave": True,
        "seguridad_grave": False,
        "accesibilidad_grave": False,
    }


def test_las_reglas_aplicadas_incluyen_su_descripcion(config):
    calculo = calcular_prioridad(puntajes(config, seguridad=3), config)
    assert calculo.reglas_aplicadas[0].descripcion == "Seguridad grave (puntaje 3)"


# --- Criterio informativo ---


@pytest.mark.parametrize("base", [{}, {"riesgo_personas": 2, "impacto_academico": 3}])
def test_el_costo_estimado_no_tiene_efecto_en_el_puntaje_ni_en_la_prioridad(config, base):
    calculos = [
        calcular_prioridad(puntajes(config, **base, costo_estimado=costo), config)
        for costo in range(4)
    ]
    assert all(c == calculos[0] for c in calculos)


# --- Precondiciones ---


@pytest.mark.parametrize(
    "alterar",
    [
        pytest.param(lambda p: p.pop("seguridad"), id="clave-faltante"),
        pytest.param(lambda p: p.update(desconocido=1), id="clave-desconocida"),
        pytest.param(lambda p: p.update(seguridad=4), id="mayor-que-3"),
        pytest.param(lambda p: p.update(seguridad=-1), id="negativo"),
        pytest.param(lambda p: p.update(seguridad=2.0), id="no-entero"),
        pytest.param(lambda p: p.update(seguridad=True), id="booleano"),
    ],
)
def test_rechaza_puntajes_invalidos(config, alterar):
    valores = puntajes(config)
    alterar(valores)
    with pytest.raises(ValueError):
        calcular_prioridad(valores, config)


def test_el_error_menciona_las_claves_problematicas(config):
    valores = puntajes(config) | {"desconocido": 1}
    del valores["seguridad"]
    with pytest.raises(ValueError, match="seguridad") as excinfo:
        calcular_prioridad(valores, config)
    assert "desconocido" in str(excinfo.value)


# --- Determinismo y monotonía ---

SUBCONJUNTO = (
    "riesgo_personas",
    "seguridad",
    "interrupcion_servicios",
    "usuarios_afectados",
    "accesibilidad",
)


def combinaciones(config):
    for valores in itertools.product(range(4), repeat=len(SUBCONJUNTO)):
        yield puntajes(config, **dict(zip(SUBCONJUNTO, valores, strict=True)))


def test_mismos_puntajes_y_configuracion_dan_siempre_el_mismo_resultado(config):
    for valores in combinaciones(config):
        assert calcular_prioridad(valores, config) == calcular_prioridad(dict(valores), config)


def test_la_prioridad_final_nunca_es_menos_urgente_que_la_del_umbral(config):
    for valores in combinaciones(config):
        calculo = calcular_prioridad(valores, config)
        assert calculo.prioridad_final <= calculo.prioridad_umbral
        cambios = [r for r in calculo.reglas_aplicadas if r.produjo_cambio]
        assert len(cambios) == (1 if calculo.prioridad_final < calculo.prioridad_umbral else 0)


def test_subir_un_puntaje_nunca_baja_la_urgencia(config):
    for valores in combinaciones(config):
        final = calcular_prioridad(valores, config).prioridad_final
        for clave in SUBCONJUNTO:
            if valores[clave] < 3:
                mayor = valores | {clave: valores[clave] + 1}
                assert calcular_prioridad(mayor, config).prioridad_final <= final
