"""Medición de aciertos sobre el dataset (comando `evaluar_dataset`)."""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from pedidos.management.commands import evaluar_dataset
from pedidos.models import Pedido
from tests.pedidos.conftest import EvaluadorFalso, evaluacion, falla

pytestmark = pytest.mark.django_db


def ejemplo(codigo: str, prioridad: str, tipo: str = "Electricidad") -> dict:
    return {
        "codigo_ejemplo": codigo,
        "canal": "formulario",
        "texto": f"Cables pelados en el pasillo ({codigo})",
        "dependencia": "Rectorado",
        "ubicacion": "Pasillo central",
        "prioridad_esperada": prioridad,
        "tipo_esperado": tipo,
    }


@pytest.fixture
def archivo(tmp_path) -> Path:
    destino = tmp_path / "dataset.json"
    contenido = [ejemplo("EJ-01", "P1"), ejemplo("EJ-02", "P3", "Mobiliario")]
    destino.write_text(json.dumps(contenido), encoding="utf-8")
    return destino


@pytest.fixture
def opciones(monkeypatch, config):
    """La IA falsa responde siempre P1 / Electricidad; anota las opciones de construcción."""
    principal = EvaluadorFalso(evaluacion(config), modelo="gemini-falso")
    respaldo = EvaluadorFalso(falla(), nombre="palabras_clave")
    llamadas: list[dict] = []

    def construir(cfg, **recibidas):
        llamadas.append(recibidas)
        return principal, respaldo

    monkeypatch.setattr(evaluar_dataset, "construir_evaluadores", construir)
    return llamadas


def ejecutar(*argumentos) -> str:
    salida = StringIO()
    call_command("evaluar_dataset", *argumentos, stdout=salida)
    return salida.getvalue()


def test_informa_los_aciertos_y_los_casos_no_coincidentes(archivo, opciones):
    salida = ejecutar(str(archivo))
    assert "Coincidencia de prioridad: 50,0 % (1 de 2)" in salida
    assert "Coincidencia de tipo principal: 50,0 % (1 de 2)" in salida
    assert "Tiempo promedio por pedido:" in salida
    assert "Casos no coincidentes (1)" in salida
    assert "EJ-02" in salida and "P3 / Mobiliario" in salida and "IA" in salida


def test_no_persiste_ningun_pedido(archivo, opciones):
    ejecutar(str(archivo))
    assert not Pedido.objects.exists()


def test_por_defecto_usa_el_cache(archivo, opciones):
    ejecutar(str(archivo))
    assert opciones == [{"usar_cache": True, "refrescar_cache": False}]


def test_sin_cache_consulta_directamente(archivo, opciones):
    ejecutar(str(archivo), "--sin-cache")
    assert opciones == [{"usar_cache": False, "refrescar_cache": False}]


def test_refrescar_regenera_el_cache_con_gemini(archivo, opciones, settings):
    settings.GEMINI_API_KEY = "clave-de-prueba"
    salida = ejecutar(str(archivo), "--refrescar-cache")
    assert opciones == [{"usar_cache": True, "refrescar_cache": True}]
    assert "Caché regenerado" in salida


def test_refrescar_sin_api_key_falla_sin_evaluar(archivo, opciones, settings):
    settings.GEMINI_API_KEY = ""
    with pytest.raises(CommandError, match="GEMINI_API_KEY"):
        ejecutar(str(archivo), "--refrescar-cache")
    assert opciones == []


def test_las_opciones_de_cache_son_excluyentes(archivo, opciones):
    with pytest.raises(CommandError):
        ejecutar(str(archivo), "--sin-cache", "--refrescar-cache")


def test_un_dataset_invalido_falla(tmp_path, opciones):
    destino = tmp_path / "dataset.json"
    destino.write_text(json.dumps([ejemplo("EJ-01", "P9")]), encoding="utf-8")
    with pytest.raises(CommandError, match="Dataset de ejemplo inválido"):
        ejecutar(str(destino))


def test_por_defecto_evalua_el_dataset_del_repositorio(opciones):
    assert "Pedidos evaluados: 18" in ejecutar()
