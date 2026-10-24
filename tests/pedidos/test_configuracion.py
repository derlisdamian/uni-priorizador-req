"""Carga de la configuración al iniciar la aplicación y comando `validar_config`."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command

from pedidos import configuracion


@pytest.fixture
def directorio(tmp_path) -> Path:
    destino = tmp_path / "config"
    shutil.copytree(settings.TRIAGE_CONFIG_DIR, destino)
    return destino


@pytest.fixture
def reiniciar(settings):
    """Simula un reinicio: vuelve a ejecutar `ready()` con otro directorio de configuración."""

    def _reiniciar(directorio: Path) -> None:
        settings.TRIAGE_CONFIG_DIR = directorio
        apps.get_app_config("pedidos").ready()

    original = settings.TRIAGE_CONFIG_DIR
    yield _reiniciar
    settings.TRIAGE_CONFIG_DIR = original
    apps.get_app_config("pedidos").ready()


def invalidar(directorio: Path) -> None:
    ruta = directorio / "criterios.yaml"
    texto = ruta.read_text(encoding="utf-8")
    ruta.write_text(texto.replace("P1: 70", "P1: 10"), encoding="utf-8")


def test_la_configuracion_se_carga_al_arrancar_y_se_comparte():
    config = configuracion.obtener()
    assert config is configuracion.obtener()
    assert len(config.claves_criterios()) == 9


def test_una_configuracion_invalida_impide_el_arranque(directorio, reiniciar):
    invalidar(directorio)
    with pytest.raises(ImproperlyConfigured, match="estrictamente decrecientes"):
        reiniciar(directorio)


def test_una_configuracion_invalida_impide_el_uso(directorio, reiniciar):
    invalidar(directorio)
    with pytest.raises(ImproperlyConfigured):
        reiniciar(directorio)
    with pytest.raises(ImproperlyConfigured, match="Configuración de triage inválida"):
        configuracion.obtener()


def test_los_cambios_se_aplican_solo_tras_reiniciar(directorio, reiniciar):
    reiniciar(directorio)
    antes = configuracion.obtener()

    ruta = directorio / "criterios.yaml"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("P3: 20", "P3: 25"), encoding="utf-8")
    assert configuracion.obtener() is antes  # sin reiniciar sigue la configuración anterior

    reiniciar(directorio)
    despues = configuracion.obtener()
    assert despues.version != antes.version
    assert despues.umbrales[2].minimo == 25


class TestComandoValidarConfig:
    def test_informa_la_version_de_una_configuracion_valida(self, capsys):
        call_command("validar_config")
        salida = capsys.readouterr().out
        assert f"Configuración válida (versión {configuracion.obtener().version})" in salida

    def test_valida_otro_directorio(self, directorio, capsys):
        call_command("validar_config", "--directorio", str(directorio))
        assert "Configuración válida" in capsys.readouterr().out

    def test_enumera_los_errores_y_falla(self, directorio):
        invalidar(directorio)
        (directorio / "tipos.yaml").write_text("tipos: []\n", encoding="utf-8")
        with pytest.raises(CommandError) as error:
            call_command("validar_config", "--directorio", str(directorio))
        assert error.value.returncode != 0
        assert "estrictamente decrecientes" in str(error.value)
        assert "la lista de tipos está vacía" in str(error.value)


class TestProcesoConConfiguracionInvalida:
    """Desde la línea de comandos, como se ejecuta realmente al arrancar."""

    def ejecutar(self, directorio: Path, *argumentos: str) -> subprocess.CompletedProcess:
        entorno = os.environ | {"TRIAGE_CONFIG_DIR": str(directorio)}
        return subprocess.run(
            [sys.executable, "manage.py", *argumentos],
            cwd=settings.BASE_DIR,
            env=entorno,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_el_servidor_no_arranca(self, directorio):
        invalidar(directorio)
        proceso = self.ejecutar(directorio, "check")
        assert proceso.returncode != 0
        assert "estrictamente decrecientes" in proceso.stderr

    def test_validar_config_diagnostica_sin_traza(self, directorio):
        invalidar(directorio)
        proceso = self.ejecutar(directorio, "validar_config")
        assert proceso.returncode == 1
        assert "estrictamente decrecientes" in proceso.stderr
        assert "Traceback" not in proceso.stderr
