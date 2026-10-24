"""Los settings de Django se leen de variables de entorno."""

import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured

VARIABLES = [
    "DJANGO_SECRET_KEY",
    "DJANGO_DEBUG",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT_S",
    "TRIAGE_USAR_CACHE",
    "TRIAGE_CONFIG_DIR",
]


@pytest.fixture
def cargar_settings(monkeypatch):
    """Recarga `sitio.settings` con un entorno controlado."""

    def _cargar(**entorno):
        for variable in VARIABLES:
            monkeypatch.delenv(variable, raising=False)
        for variable, valor in entorno.items():
            monkeypatch.setenv(variable, valor)
        import sitio.settings

        return importlib.reload(sitio.settings)

    yield _cargar
    # Restaura el módulo con el entorno original para los demás tests.
    monkeypatch.undo()
    import sitio.settings

    importlib.reload(sitio.settings)


def test_lee_secret_key_y_debug_del_entorno(cargar_settings):
    settings = cargar_settings(DJANGO_SECRET_KEY="clave-de-prueba", DJANGO_DEBUG="1")
    assert settings.SECRET_KEY == "clave-de-prueba"
    assert settings.DEBUG is True


@pytest.mark.parametrize("valor", ["0", "false", "no", ""])
def test_debug_desactivado(cargar_settings, valor):
    settings = cargar_settings(DJANGO_SECRET_KEY="x", DJANGO_DEBUG=valor)
    assert settings.DEBUG is False


def test_sin_secret_key_y_sin_debug_no_arranca(cargar_settings):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        cargar_settings(DJANGO_DEBUG="0")


def test_sin_secret_key_en_debug_genera_una_clave_efimera(cargar_settings):
    settings = cargar_settings(DJANGO_DEBUG="1")
    assert len(settings.SECRET_KEY) >= 50


def test_conexion_a_postgresql_en_el_servicio_db(cargar_settings):
    settings = cargar_settings(
        DJANGO_SECRET_KEY="x",
        POSTGRES_DB="triage",
        POSTGRES_USER="usuario",
        POSTGRES_PASSWORD="secreto",
    )
    base = settings.DATABASES["default"]
    assert base["ENGINE"] == "django.db.backends.postgresql"
    assert base["NAME"] == "triage"
    assert base["USER"] == "usuario"
    assert base["PASSWORD"] == "secreto"
    assert base["HOST"] == "db"
    assert base["PORT"] == "5432"


def test_host_y_puerto_de_postgresql_configurables(cargar_settings):
    settings = cargar_settings(
        DJANGO_SECRET_KEY="x", POSTGRES_HOST="localhost", POSTGRES_PORT="5433"
    )
    assert settings.DATABASES["default"]["HOST"] == "localhost"
    assert settings.DATABASES["default"]["PORT"] == "5433"


def test_valores_por_defecto_de_gemini_y_triage(cargar_settings):
    settings = cargar_settings(DJANGO_SECRET_KEY="x")
    assert settings.GEMINI_API_KEY == ""
    assert settings.GEMINI_MODEL == "gemini-3.8-flash"
    assert settings.GEMINI_TIMEOUT_S == 4.0
    assert settings.TRIAGE_USAR_CACHE is False
    assert settings.TRIAGE_CONFIG_DIR == settings.BASE_DIR / "config"
    assert settings.TRIAGE_CACHE_ARCHIVO == settings.BASE_DIR / "data/cache/evaluaciones.json"


def test_gemini_y_triage_se_leen_del_entorno(cargar_settings, tmp_path):
    settings = cargar_settings(
        DJANGO_SECRET_KEY="x",
        GEMINI_API_KEY="api-key-de-prueba",
        GEMINI_MODEL="gemini-3.5-flash-lite",
        GEMINI_TIMEOUT_S="2.5",
        TRIAGE_USAR_CACHE="1",
        TRIAGE_CONFIG_DIR=str(tmp_path),
    )
    assert settings.GEMINI_API_KEY == "api-key-de-prueba"
    assert settings.GEMINI_MODEL == "gemini-3.5-flash-lite"
    assert settings.GEMINI_TIMEOUT_S == 2.5
    assert settings.TRIAGE_USAR_CACHE is True
    assert settings.TRIAGE_CONFIG_DIR == tmp_path


def test_interfaz_en_espanol_con_zona_horaria_local(cargar_settings):
    settings = cargar_settings(DJANGO_SECRET_KEY="x")
    assert settings.LANGUAGE_CODE == "es"
    assert settings.TIME_ZONE == "America/Argentina/Buenos_Aires"
    assert settings.USE_TZ is True


def test_app_de_pedidos_instalada():
    from django.apps import apps

    assert apps.is_installed("pedidos")
