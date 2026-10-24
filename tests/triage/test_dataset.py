"""Dataset etiquetado de ejemplo (`triage.dataset`) y su archivo `data/pedidos_ejemplo.json`."""

import json
from collections import Counter
from pathlib import Path

import pytest

from triage.config import ConfiguracionTriage, cargar_configuracion
from triage.dataset import (
    DatasetInvalido,
    PedidoEjemplo,
    cargar_dataset,
    formatear_reporte,
    medir_aciertos,
)
from triage.evaluadores import ErrorEvaluacion, TipoErrorEvaluacion
from triage.schemas import (
    Canal,
    EntradaEvaluacion,
    EvaluacionCriterios,
    OrigenResultado,
    Prioridad,
    PuntajeCriterio,
)

RAIZ = Path(__file__).resolve().parents[2]
DATASET = RAIZ / "data" / "pedidos_ejemplo.json"


@pytest.fixture(scope="module")
def config() -> ConfiguracionTriage:
    return cargar_configuracion(RAIZ / "config")


@pytest.fixture(scope="module")
def ejemplos(config):
    return cargar_dataset(DATASET, config)


def ejemplo(**cambios) -> dict:
    valores = {
        "codigo_ejemplo": "EJ-01",
        "canal": "formulario",
        "texto": "Cables pelados en el pasillo",
        "dependencia": "Rectorado",
        "ubicacion": None,
        "prioridad_esperada": "P1",
        "tipo_esperado": "Electricidad",
    }
    return valores | cambios


def escribir(tmp_path, contenido) -> Path:
    archivo = tmp_path / "dataset.json"
    archivo.write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")
    return archivo


class TestCargarDataset:
    def test_lee_los_ejemplos_y_acepta_la_prioridad_por_nombre(self, tmp_path, config):
        [leido] = cargar_dataset(escribir(tmp_path, [ejemplo()]), config)
        assert leido.codigo_ejemplo == "EJ-01"
        assert leido.canal is Canal.FORMULARIO
        assert leido.prioridad_esperada is Prioridad.P1
        assert leido.tipo_esperado == "Electricidad"
        assert leido.caso is None

    def test_rechaza_una_estructura_invalida_enumerando_los_errores(self, tmp_path, config):
        contenido = [ejemplo(prioridad_esperada="P5"), ejemplo(codigo_ejemplo="EJ-02", texto=1)]
        with pytest.raises(DatasetInvalido) as error:
            cargar_dataset(escribir(tmp_path, contenido), config)
        assert len(error.value.errores) == 2

    def test_rechaza_campos_desconocidos(self, tmp_path, config):
        with pytest.raises(DatasetInvalido):
            cargar_dataset(escribir(tmp_path, [ejemplo(contacto="ana@uni.edu.ar")]), config)

    def test_rechaza_un_tipo_que_no_esta_configurado(self, tmp_path, config):
        with pytest.raises(DatasetInvalido, match="Gas"):
            cargar_dataset(escribir(tmp_path, [ejemplo(tipo_esperado="Gas")]), config)

    def test_rechaza_codigos_repetidos(self, tmp_path, config):
        with pytest.raises(DatasetInvalido, match="EJ-01"):
            cargar_dataset(escribir(tmp_path, [ejemplo(), ejemplo()]), config)

    def test_rechaza_un_texto_vacio(self, tmp_path, config):
        with pytest.raises(DatasetInvalido):
            cargar_dataset(escribir(tmp_path, [ejemplo(texto="   ")]), config)

    def test_rechaza_un_json_mal_formado(self, tmp_path, config):
        archivo = tmp_path / "dataset.json"
        archivo.write_text("[{", encoding="utf-8")
        with pytest.raises(DatasetInvalido):
            cargar_dataset(archivo, config)


class TestDatasetDeEjemplo:
    """El dataset versionado cumple la composición pedida (requisito 11.1)."""

    def test_tiene_entre_15_y_20_pedidos(self, ejemplos):
        assert 15 <= len(ejemplos) <= 20

    def test_cubre_cada_prioridad_con_al_menos_3_pedidos(self, ejemplos):
        por_prioridad = Counter(e.prioridad_esperada for e in ejemplos)
        assert all(por_prioridad[p] >= 3 for p in Prioridad), por_prioridad

    def test_cubre_al_menos_7_de_los_9_tipos(self, ejemplos, config):
        assert len({e.tipo_esperado for e in ejemplos}) >= 7
        assert len(config.tipos) == 9

    def test_incluye_un_caso_por_cada_regla_de_escalamiento(self, ejemplos, config):
        casos = {e.caso for e in ejemplos}
        assert {f"regla:{r.id}" for r in config.reglas} <= casos

    def test_incluye_un_texto_ambiguo_de_baja_confianza(self, ejemplos):
        assert "ambiguo" in {e.caso for e in ejemplos}

    def test_incluye_un_texto_libre_sin_dependencia(self, ejemplos):
        assert any(e.canal is Canal.TEXTO_LIBRE and e.dependencia is None for e in ejemplos)

    def test_no_incluye_datos_de_contacto(self, ejemplos):
        assert not any("@" in e.texto for e in ejemplos)


def evaluacion(config, tipo: str, **puntajes) -> EvaluacionCriterios:
    return EvaluacionCriterios(
        descripcion_normalizada="Pedido de prueba",
        dependencia="Rectorado",
        ubicacion="Pasillo central",
        tipo_principal=tipo,
        tipos_secundarios=[],
        criterios={
            clave: PuntajeCriterio(puntaje=puntajes.get(clave, 0), evidencia=["de prueba"])
            for clave in config.claves_criterios()
        },
        confianza=0.9,
        texto_insuficiente=False,
        conflicto_tipos=False,
    )


class EvaluadorPorTexto:
    """Responde según el texto recibido: una evaluación o una excepción."""

    def __init__(self, respuestas: dict, nombre="gemini:falso"):
        self.respuestas = respuestas
        self.textos: list[str] = []
        self._nombre = nombre
        self.modelo = "gemini-falso"

    @property
    def nombre(self) -> str:
        return self._nombre

    def evaluar(self, entrada: EntradaEvaluacion) -> EvaluacionCriterios:
        self.textos.append(entrada.texto)
        respuesta = self.respuestas[entrada.texto]
        if isinstance(respuesta, BaseException):
            raise respuesta
        return respuesta


def pedido(codigo, texto, prioridad, tipo) -> PedidoEjemplo:
    return PedidoEjemplo(
        codigo_ejemplo=codigo,
        canal=Canal.FORMULARIO,
        texto=texto,
        dependencia="Rectorado",
        ubicacion="Pasillo central",
        prioridad_esperada=prioridad,
        tipo_esperado=tipo,
    )


class Reloj:
    """Avanza medio segundo en cada lectura: cada triage dura 500 ms."""

    def __init__(self):
        self.ahora = 0.0

    def __call__(self) -> float:
        self.ahora += 0.5
        return self.ahora


@pytest.fixture
def reporte(config):
    ejemplos = [
        pedido("EJ-01", "cables pelados", "P1", "Electricidad"),  # coincide todo
        pedido("EJ-02", "sillas rotas", "P3", "Mobiliario"),  # falla la prioridad
        pedido("EJ-03", "proyector", "P4", "Infraestructura"),  # falla el tipo
        pedido("EJ-04", "nada", "P4", "Mobiliario"),  # ni IA ni respaldo: sin clasificar
    ]
    principal = EvaluadorPorTexto(
        {
            "cables pelados": evaluacion(config, "Electricidad", riesgo_personas=3),
            "sillas rotas": evaluacion(config, "Mobiliario"),
            "proyector": evaluacion(config, "TIC"),
            "nada": ErrorEvaluacion(TipoErrorEvaluacion.SERVICIO, "503"),
        }
    )
    sin_coincidencias = ErrorEvaluacion(TipoErrorEvaluacion.SIN_COINCIDENCIAS, "ningún tipo")
    respaldo = EvaluadorPorTexto({"nada": sin_coincidencias}, nombre="palabras_clave")
    return medir_aciertos(ejemplos, principal, respaldo, config, reloj=Reloj())


class TestMedirAciertos:
    def test_compara_la_prioridad_final_y_el_tipo_principal(self, reporte):
        coincidencias = {
            r.codigo_ejemplo: (r.coincide_prioridad, r.coincide_tipo) for r in reporte.resultados
        }
        assert coincidencias == {
            "EJ-01": (True, True),
            "EJ-02": (False, True),
            "EJ-03": (True, False),
            "EJ-04": (False, False),
        }

    def test_calcula_los_porcentajes_de_coincidencia(self, reporte):
        assert reporte.porcentaje_prioridad == 50.0
        assert reporte.porcentaje_tipo == 50.0

    def test_informa_el_tiempo_por_pedido_y_su_promedio(self, reporte):
        assert [r.duracion_ms for r in reporte.resultados] == [500, 500, 500, 500]
        assert reporte.duracion_promedio_ms == 500

    def test_los_no_coincidentes_conservan_lo_obtenido_y_el_origen(self, reporte):
        assert [r.codigo_ejemplo for r in reporte.no_coincidentes] == ["EJ-02", "EJ-03", "EJ-04"]
        sin_clasificar = reporte.no_coincidentes[-1]
        assert sin_clasificar.prioridad_obtenida is None
        assert sin_clasificar.tipo_obtenido is None
        assert sin_clasificar.origen is OrigenResultado.SIN_CLASIFICACION
        assert reporte.no_coincidentes[0].prioridad_obtenida is Prioridad.P4
        assert reporte.no_coincidentes[0].origen is OrigenResultado.IA

    def test_un_dataset_vacio_no_divide_por_cero(self, config):
        vacio = medir_aciertos([], EvaluadorPorTexto({}), EvaluadorPorTexto({}), config)
        assert (vacio.porcentaje_prioridad, vacio.porcentaje_tipo) == (0.0, 0.0)
        assert vacio.duracion_promedio_ms == 0


class TestFormatearReporte:
    def test_resume_los_aciertos_los_tiempos_y_los_no_coincidentes(self, reporte):
        texto = formatear_reporte(reporte)
        assert "Coincidencia de prioridad: 50,0 % (2 de 4)" in texto
        assert "Coincidencia de tipo principal: 50,0 % (2 de 4)" in texto
        assert "Tiempo promedio por pedido: 500 ms" in texto
        assert "EJ-01" in texto  # el tiempo de cada pedido
        assert "Casos no coincidentes (3)" in texto
        assert "P3 / Mobiliario" in texto and "P4 / Mobiliario" in texto  # esperado y obtenido
        assert "sin clasificar" in texto and "Sin clasificación" in texto

    def test_sin_casos_no_coincidentes_lo_indica(self, config):
        ejemplos = [pedido("EJ-01", "cables pelados", "P1", "Electricidad")]
        principal = EvaluadorPorTexto(
            {"cables pelados": evaluacion(config, "Electricidad", riesgo_personas=3)}
        )
        reporte = medir_aciertos(ejemplos, principal, EvaluadorPorTexto({}), config)
        assert "Todos los casos coinciden" in formatear_reporte(reporte)
