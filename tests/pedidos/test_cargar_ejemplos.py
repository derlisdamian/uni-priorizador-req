"""Carga del dataset de ejemplo en la bandeja (comando `cargar_ejemplos`)."""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from pedidos.consultas import FiltrosBandeja, consultar_bandeja
from pedidos.management.commands import cargar_ejemplos
from pedidos.models import Pedido
from tests.pedidos.conftest import EvaluadorFalso, evaluacion, falla
from triage.schemas import Canal, Prioridad

pytestmark = pytest.mark.django_db

DATASET = Path(__file__).resolve().parents[2] / "data" / "pedidos_ejemplo.json"


def ejemplo(codigo: str, **cambios) -> dict:
    valores = {
        "codigo_ejemplo": codigo,
        "canal": "formulario",
        "texto": f"Cables pelados en el pasillo ({codigo})",
        "dependencia": "Rectorado",
        "ubicacion": "Pasillo central",
        "prioridad_esperada": "P1",
        "tipo_esperado": "Electricidad",
    }
    return valores | cambios


@pytest.fixture
def archivo(tmp_path) -> Path:
    contenido = [ejemplo("EJ-01"), ejemplo("EJ-02", canal="texto_libre", dependencia=None)]
    destino = tmp_path / "dataset.json"
    destino.write_text(json.dumps(contenido), encoding="utf-8")
    return destino


@pytest.fixture
def evaluadores(monkeypatch, config):
    """Reemplaza los evaluadores del comando y anota con qué opciones se construyeron."""
    principal = EvaluadorFalso(evaluacion(config), modelo="gemini-falso")
    respaldo = EvaluadorFalso(falla(), nombre="palabras_clave")
    llamadas: list[dict] = []

    def construir(cfg, **opciones):
        llamadas.append(opciones)
        return principal, respaldo

    monkeypatch.setattr(cargar_ejemplos, "construir_evaluadores", construir)
    return principal, llamadas


def ejecutar(**opciones) -> str:
    salida = StringIO()
    call_command("cargar_ejemplos", stdout=salida, **opciones)
    return salida.getvalue()


def test_registra_y_prioriza_cada_ejemplo_con_su_codigo(archivo, evaluadores):
    principal, _ = evaluadores
    salida = ejecutar(archivo=archivo)

    pedidos = {p.codigo_ejemplo: p for p in Pedido.objects.all()}
    assert set(pedidos) == {"EJ-01", "EJ-02"}
    assert pedidos["EJ-02"].canal == Canal.TEXTO_LIBRE
    assert all(p.prioridad_vigente == Prioridad.P1 for p in pedidos.values())
    assert all(hasattr(p, "resultado") for p in pedidos.values())
    assert len(principal.entradas) == 2
    assert "2 cargados" in salida


def test_usa_el_evaluador_con_cache(archivo, evaluadores):
    _, llamadas = evaluadores
    ejecutar(archivo=archivo)
    assert llamadas == [{"usar_cache": True}]


def test_es_idempotente_y_omite_los_ejemplos_ya_cargados(archivo, evaluadores):
    principal, _ = evaluadores
    ejecutar(archivo=archivo)
    salida = ejecutar(archivo=archivo)

    assert Pedido.objects.count() == 2
    assert len(principal.entradas) == 2  # la segunda vez no se evalúa nada
    assert "0 cargados" in salida and "2 omitidos" in salida


def test_los_ejemplos_aparecen_en_la_bandeja(archivo, evaluadores):
    ejecutar(archivo=archivo)
    codigos = {p.codigo_ejemplo for p in consultar_bandeja(FiltrosBandeja())}
    assert codigos == {"EJ-01", "EJ-02"}


def test_un_dataset_invalido_falla_sin_cargar_nada(tmp_path, evaluadores):
    destino = tmp_path / "dataset.json"
    destino.write_text(json.dumps([ejemplo("EJ-01", tipo_esperado="Gas")]), encoding="utf-8")
    with pytest.raises(CommandError, match="Gas"):
        ejecutar(archivo=destino)
    assert not Pedido.objects.exists()


def test_por_defecto_carga_el_dataset_del_repositorio(evaluadores):
    ejecutar()
    cantidad = len(json.loads(DATASET.read_text(encoding="utf-8")))
    assert Pedido.objects.exclude(codigo_ejemplo=None).count() == cantidad
