"""Carga y validación de la configuración institucional (`triage.config`)."""

import copy
from pathlib import Path

import pytest
import yaml

from triage.config import ConfiguracionInvalida, ConfiguracionTriage, cargar_configuracion
from triage.schemas import Prioridad

DIRECTORIO_INICIAL = Path(__file__).resolve().parents[2] / "config"


def leer_inicial(nombre: str) -> dict:
    return yaml.safe_load((DIRECTORIO_INICIAL / nombre).read_text(encoding="utf-8"))


@pytest.fixture
def criterios() -> dict:
    return leer_inicial("criterios.yaml")


@pytest.fixture
def tipos() -> dict:
    return leer_inicial("tipos.yaml")


@pytest.fixture
def escribir(tmp_path):
    """Escribe los YAML en un directorio temporal y devuelve su ruta."""

    def _escribir(criterios: dict, tipos: dict) -> Path:
        for nombre, contenido in (("criterios.yaml", criterios), ("tipos.yaml", tipos)):
            (tmp_path / nombre).write_text(
                yaml.safe_dump(contenido, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
        return tmp_path

    return _escribir


def errores_al_cargar(directorio: Path) -> list[str]:
    with pytest.raises(ConfiguracionInvalida) as excinfo:
        cargar_configuracion(directorio)
    return excinfo.value.errores


def criterio(datos: dict, clave: str) -> dict:
    return next(c for c in datos["criterios"] if c["clave"] == clave)


# --- Configuración inicial ---


@pytest.fixture(scope="module")
def inicial() -> ConfiguracionTriage:
    return cargar_configuracion(DIRECTORIO_INICIAL)


def test_la_configuracion_inicial_tiene_los_nueve_criterios_con_sus_pesos(inicial):
    pesos = {c.clave: c.peso for c in inicial.criterios}
    assert pesos == {
        "riesgo_personas": 22,
        "seguridad": 14,
        "interrupcion_servicios": 12,
        "impacto_academico": 12,
        "usuarios_afectados": 10,
        "deterioro_progresivo": 10,
        "urgencia_temporal": 10,
        "accesibilidad": 10,
        "costo_estimado": 0,
    }
    assert inicial.claves_criterios() == list(pesos)


def test_costo_estimado_es_el_unico_criterio_informativo(inicial):
    assert [c.clave for c in inicial.criterios if c.informativo] == ["costo_estimado"]


def test_todos_los_criterios_tienen_nombre_legible(inicial):
    for c in inicial.criterios:
        assert c.nombre and c.nombre != c.clave


def test_los_criterios_que_suman_tienen_senales_de_respaldo(inicial):
    for c in inicial.criterios:
        if not c.informativo:
            assert c.senales_respaldo, c.clave
            assert all(0 <= s.puntaje <= 3 for s in c.senales_respaldo)


def test_umbrales_iniciales(inicial):
    assert [(u.prioridad, u.minimo) for u in inicial.umbrales] == [
        (Prioridad.P1, 70),
        (Prioridad.P2, 45),
        (Prioridad.P3, 20),
    ]


def test_reglas_de_escalamiento_iniciales(inicial):
    reglas = {r.id: r for r in inicial.reglas}
    assert list(reglas) == [
        "riesgo_personas_grave",
        "seguridad_grave",
        "accesibilidad_grave",
        "interrupcion_masiva",
    ]
    assert reglas["riesgo_personas_grave"].prioridad_minima is Prioridad.P1
    assert reglas["seguridad_grave"].prioridad_minima is Prioridad.P1
    assert reglas["accesibilidad_grave"].prioridad_minima is Prioridad.P2
    masiva = reglas["interrupcion_masiva"]
    assert masiva.prioridad_minima is Prioridad.P2
    assert [(c.criterio, c.operador, c.valor) for c in masiva.condiciones] == [
        ("interrupcion_servicios", "igual", 3),
        ("usuarios_afectados", "mayor_o_igual", 2),
    ]
    assert all(r.descripcion for r in inicial.reglas)


def test_confianza_minima_inicial(inicial):
    assert inicial.confianza_minima == 0.6


def test_los_nueve_tipos_iniciales_tienen_senales(inicial):
    assert inicial.nombres_tipos() == [
        "Electricidad",
        "Sanitaria",
        "Cubierta",
        "Climatización",
        "Accesibilidad",
        "Mobiliario",
        "Infraestructura",
        "TIC",
        "Seguridad",
    ]
    assert all(t.senales for t in inicial.tipos)


def test_la_configuracion_es_inmutable(inicial):
    with pytest.raises(Exception):  # noqa: B017 - Pydantic lanza ValidationError
        inicial.confianza_minima = 0.9


# --- Versión ---


def test_la_version_es_corta_y_estable(inicial):
    assert len(inicial.version) == 12
    assert all(c in "0123456789abcdef" for c in inicial.version)
    assert cargar_configuracion(DIRECTORIO_INICIAL).version == inicial.version


def test_la_version_cambia_con_el_contenido(escribir, criterios, tipos, inicial):
    criterio(criterios, "riesgo_personas")["nombre"] = "Riesgo para personas"
    assert cargar_configuracion(escribir(criterios, tipos)).version != inicial.version


# --- Configuración inválida ---


def test_regla_con_criterio_desconocido(escribir, criterios, tipos):
    criterios["reglas"][0]["condiciones"][0]["criterio"] = "inexistente"
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("inexistente" in e and "desconocido" in e for e in errores)


def test_criterio_duplicado(escribir, criterios, tipos):
    duplicado = copy.deepcopy(criterio(criterios, "costo_estimado"))
    criterios["criterios"].append(duplicado)
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("costo_estimado" in e and "duplicado" in e for e in errores)


def test_peso_negativo(escribir, criterios, tipos):
    criterio(criterios, "seguridad")["peso"] = -14
    criterio(criterios, "riesgo_personas")["peso"] = 50  # la suma sigue siendo 100
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("seguridad" in e and "negativo" in e for e in errores)


@pytest.mark.parametrize("peso", [12.5, "doce", True])
def test_peso_no_entero(escribir, criterios, tipos, peso):
    criterio(criterios, "impacto_academico")["peso"] = peso
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("peso" in e and "entero" in e for e in errores)


def test_pesos_que_no_suman_100(escribir, criterios, tipos):
    criterio(criterios, "accesibilidad")["peso"] = 11
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("101" in e and "100" in e for e in errores)


def test_criterio_informativo_con_peso(escribir, criterios, tipos):
    criterio(criterios, "costo_estimado")["peso"] = 5
    criterio(criterios, "riesgo_personas")["peso"] = 17
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("costo_estimado" in e and "informativo" in e for e in errores)


def test_criterio_informativo_usado_en_una_regla(escribir, criterios, tipos):
    criterios["reglas"][0]["condiciones"][0]["criterio"] = "costo_estimado"
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("costo_estimado" in e and "informativo" in e for e in errores)


@pytest.mark.parametrize(
    "umbrales",
    [
        {"P1": 45, "P2": 70, "P3": 20},
        {"P1": 70, "P2": 45, "P3": 45},
        {"P1": 70, "P2": 20, "P3": 45},
    ],
)
def test_umbrales_no_decrecientes(escribir, criterios, tipos, umbrales):
    criterios["umbrales"] = umbrales
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("umbrales" in e and "decrecientes" in e for e in errores)


def test_umbrales_incompletos(escribir, criterios, tipos):
    criterios["umbrales"] = {"P1": 70, "P2": 45}
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("umbrales" in e and "P3" in e for e in errores)


@pytest.mark.parametrize("valor", [-1, 4])
def test_regla_con_valor_fuera_de_rango(escribir, criterios, tipos, valor):
    criterios["reglas"][2]["condiciones"][0]["valor"] = valor
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("accesibilidad_grave" in e and "0" in e and "3" in e for e in errores)


def test_senal_de_respaldo_con_puntaje_fuera_de_rango(escribir, criterios, tipos):
    criterio(criterios, "seguridad")["senales_respaldo"][0]["puntaje"] = 5
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("seguridad" in e and "0" in e and "3" in e for e in errores)


def test_regla_sin_condiciones(escribir, criterios, tipos):
    criterios["reglas"][0]["condiciones"] = []
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("riesgo_personas_grave" in e and "condiciones" in e for e in errores)


def test_regla_con_prioridad_minima_invalida(escribir, criterios, tipos):
    criterios["reglas"][0]["prioridad_minima"] = "P5"
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("prioridad_minima" in e for e in errores)


def test_regla_con_operador_desconocido(escribir, criterios, tipos):
    criterios["reglas"][0]["condiciones"][0]["operador"] = "menor"
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("operador" in e for e in errores)


@pytest.mark.parametrize("confianza", [-0.1, 1.5])
def test_confianza_minima_fuera_de_rango(escribir, criterios, tipos, confianza):
    criterios["confianza_minima"] = confianza
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("confianza_minima" in e for e in errores)


def test_lista_de_tipos_vacia(escribir, criterios, tipos):
    tipos["tipos"] = []
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("tipos" in e and "vacía" in e for e in errores)


def test_tipo_con_nombre_vacio(escribir, criterios, tipos):
    tipos["tipos"][0]["nombre"] = "  "
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("tipo" in e and "vacío" in e for e in errores)


def test_tipos_duplicados(escribir, criterios, tipos):
    tipos["tipos"].append({"nombre": "electricidad", "senales": ["enchufe"]})
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("electricidad" in e.lower() and "duplicado" in e for e in errores)


def test_se_enumeran_todos_los_errores_juntos(escribir, criterios, tipos):
    criterio(criterios, "seguridad")["peso"] = -14
    criterios["umbrales"] = {"P1": 20, "P2": 45, "P3": 70}
    criterios["confianza_minima"] = 2
    tipos["tipos"] = []
    with pytest.raises(ConfiguracionInvalida) as excinfo:
        cargar_configuracion(escribir(criterios, tipos))
    assert len(excinfo.value.errores) >= 4
    for error in excinfo.value.errores:
        assert error in str(excinfo.value)


def test_campo_desconocido(escribir, criterios, tipos):
    criterio(criterios, "seguridad")["pesos"] = 14
    errores = errores_al_cargar(escribir(criterios, tipos))
    assert any("pesos" in e for e in errores)


def test_archivo_faltante(tmp_path, tipos, escribir, criterios):
    directorio = escribir(criterios, tipos)
    (directorio / "tipos.yaml").unlink()
    errores = errores_al_cargar(directorio)
    assert any("tipos.yaml" in e for e in errores)


def test_yaml_mal_formado(escribir, criterios, tipos):
    directorio = escribir(criterios, tipos)
    (directorio / "criterios.yaml").write_text("criterios: [\n", encoding="utf-8")
    errores = errores_al_cargar(directorio)
    assert any("criterios.yaml" in e for e in errores)
