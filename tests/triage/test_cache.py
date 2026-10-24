"""Caché de evaluaciones persistido en un archivo versionable (`triage.evaluadores.cache`)."""

import json
import os

import pytest

from triage.evaluadores import ErrorEvaluacion, EvaluadorPedidos, TipoErrorEvaluacion
from triage.evaluadores.cache import EvaluadorConCache, envolver_con_cache
from triage.schemas import Canal, EntradaEvaluacion, EvaluacionCriterios, PuntajeCriterio


def evaluacion(tipo: str = "Electricidad") -> EvaluacionCriterios:
    return EvaluacionCriterios(
        descripcion_normalizada="Cables pelados en el pasillo",
        dependencia="Rectorado",
        ubicacion=None,
        tipo_principal=tipo,
        tipos_secundarios=[],
        criterios={"riesgo_personas": PuntajeCriterio(puntaje=3, evidencia=["cables pelados"])},
        confianza=0.8,
        texto_insuficiente=False,
        conflicto_tipos=False,
    )


class EvaluadorFalso:
    def __init__(self, modelo="gemini-a", version_prompt="v1", resultado=None, error=None):
        self.modelo = modelo
        self.version_prompt = version_prompt
        self.resultado = resultado or evaluacion()
        self.error = error
        self.llamadas = 0

    @property
    def nombre(self) -> str:
        return f"gemini:{self.modelo}"

    def evaluar(self, entrada: EntradaEvaluacion) -> EvaluacionCriterios:
        self.llamadas += 1
        if self.error:
            raise self.error
        return self.resultado


def entrada(texto: str = "Hay cables pelados en el pasillo") -> EntradaEvaluacion:
    return EntradaEvaluacion(
        texto=texto,
        canal=Canal.FORMULARIO,
        dependencia_informada="Rectorado",
        ubicacion_informada=None,
    )


@pytest.fixture
def archivo(tmp_path):
    return tmp_path / "cache" / "evaluaciones.json"


def test_cumple_el_puerto_y_conserva_el_modelo_del_evaluador_interno(archivo):
    cache = EvaluadorConCache(EvaluadorFalso(), archivo)
    assert isinstance(cache, EvaluadorPedidos)
    assert cache.nombre == "cache+gemini:gemini-a"
    assert cache.modelo == "gemini-a"
    assert cache.version_prompt == "v1"


def test_un_fallo_consulta_al_evaluador_interno_y_guarda_la_evaluacion(archivo):
    interno = EvaluadorFalso()
    resultado = EvaluadorConCache(interno, archivo).evaluar(entrada())
    assert resultado == interno.resultado
    assert interno.llamadas == 1
    guardado = json.loads(archivo.read_text(encoding="utf-8"))
    assert list(guardado.values()) == [interno.resultado.model_dump(mode="json")]


def test_un_acierto_reutiliza_la_evaluacion_sin_consultar_al_evaluador(archivo):
    interno = EvaluadorFalso()
    cache = EvaluadorConCache(interno, archivo)
    primera = cache.evaluar(entrada())
    segunda = cache.evaluar(entrada())
    assert segunda == primera
    assert interno.llamadas == 1


def test_el_cache_persiste_entre_instancias(archivo):
    EvaluadorConCache(EvaluadorFalso(), archivo).evaluar(entrada())
    otro = EvaluadorFalso(resultado=evaluacion("TIC"))
    resultado = EvaluadorConCache(otro, archivo).evaluar(entrada())
    assert resultado.tipo_principal == "Electricidad"
    assert otro.llamadas == 0


def test_un_texto_distinto_no_acierta(archivo):
    interno = EvaluadorFalso()
    cache = EvaluadorConCache(interno, archivo)
    cache.evaluar(entrada("Hay cables pelados en el pasillo"))
    cache.evaluar(entrada("Pérdida de agua en el baño"))
    assert interno.llamadas == 2
    assert len(json.loads(archivo.read_text(encoding="utf-8"))) == 2


@pytest.mark.parametrize(
    "cambio", [{"modelo": "gemini-b"}, {"version_prompt": "v2"}], ids=["modelo", "prompt"]
)
def test_cambiar_el_modelo_o_el_prompt_invalida_el_cache(archivo, cambio):
    EvaluadorConCache(EvaluadorFalso(), archivo).evaluar(entrada())
    nuevo = EvaluadorFalso(**cambio)
    EvaluadorConCache(nuevo, archivo).evaluar(entrada())
    assert nuevo.llamadas == 1


def test_los_errores_del_evaluador_se_propagan_y_no_se_guardan(archivo):
    error = ErrorEvaluacion(TipoErrorEvaluacion.TIMEOUT, "lento")
    interno = EvaluadorFalso(error=error)
    cache = EvaluadorConCache(interno, archivo)
    for _ in range(2):
        with pytest.raises(ErrorEvaluacion):
            cache.evaluar(entrada())
    assert interno.llamadas == 2
    assert not archivo.exists()


def test_la_escritura_es_atomica_y_no_deja_temporales(archivo, monkeypatch):
    cache = EvaluadorConCache(EvaluadorFalso(), archivo)
    cache.evaluar(entrada("primero"))
    contenido_previo = archivo.read_bytes()

    def reemplazo_fallido(origen, destino):
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", reemplazo_fallido)
    with pytest.raises(OSError):
        cache.evaluar(entrada("segundo"))
    assert archivo.read_bytes() == contenido_previo
    assert [p.name for p in archivo.parent.iterdir()] == [archivo.name]


def test_el_archivo_es_estable_para_versionarlo(archivo, tmp_path):
    otro_archivo = tmp_path / "otro.json"
    for destino, textos in ((archivo, ["b", "a"]), (otro_archivo, ["a", "b"])):
        cache = EvaluadorConCache(EvaluadorFalso(), destino)
        for texto in textos:
            cache.evaluar(entrada(texto))
    assert archivo.read_bytes() == otro_archivo.read_bytes()
    assert archivo.read_text(encoding="utf-8").endswith("\n")


def test_envolver_con_cache_respeta_la_configuracion(archivo):
    interno = EvaluadorFalso()
    assert envolver_con_cache(interno, usar_cache=False, archivo=archivo) is interno
    envuelto = envolver_con_cache(interno, usar_cache=True, archivo=archivo)
    assert isinstance(envuelto, EvaluadorConCache)
    assert envuelto.nombre == "cache+gemini:gemini-a"
