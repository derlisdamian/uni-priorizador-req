"""La aplicación y la base de datos se levantan con Docker Compose."""

from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((RAIZ / "docker-compose.yml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (RAIZ / "Dockerfile").read_text(encoding="utf-8")


def test_base_postgresql_17_con_volumen_nombrado(compose):
    db = compose["services"]["db"]
    assert db["image"] == "postgres:17"
    assert "pgdata:/var/lib/postgresql/data" in db["volumes"]
    assert "pgdata" in compose["volumes"]


def test_base_con_healthcheck_de_disponibilidad(compose):
    prueba = " ".join(compose["services"]["db"]["healthcheck"]["test"])
    assert "pg_isready" in prueba


def test_base_exige_contrasena_definida(compose):
    entorno = compose["services"]["db"]["environment"]
    assert entorno["POSTGRES_PASSWORD"].startswith("${POSTGRES_PASSWORD:?")


def test_web_espera_a_que_la_base_este_sana(compose):
    web = compose["services"]["web"]
    assert web["depends_on"]["db"]["condition"] == "service_healthy"


def test_web_lee_el_entorno_y_se_conecta_al_servicio_db(compose):
    web = compose["services"]["web"]
    assert ".env" in web["env_file"]
    assert web["environment"]["POSTGRES_HOST"] == "db"


def test_web_migra_y_levanta_el_servidor_accesible_desde_el_host(compose):
    web = compose["services"]["web"]
    comando = " ".join(web["command"]) if isinstance(web["command"], list) else web["command"]
    assert comando.index("manage.py migrate") < comando.index("manage.py runserver 0.0.0.0:8000")
    assert "8000:8000" in web["ports"]


def test_web_monta_el_codigo_para_recarga_en_caliente(compose):
    web = compose["services"]["web"]
    assert web["build"] == "."
    assert ".:/app" in web["volumes"]


def test_imagen_python_312_slim_con_dependencias_por_uv(dockerfile):
    assert dockerfile.splitlines()[0].startswith("FROM python:3.12-slim")
    assert "uv sync --locked" in dockerfile
    # El entorno virtual vive fuera de /app para que el código montado no lo tape.
    assert "UV_PROJECT_ENVIRONMENT=/opt/venv" in dockerfile


def test_contexto_de_build_excluye_entorno_local_y_secretos():
    ignorados = (RAIZ / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert {".env", ".venv", ".git"} <= set(ignorados)


def test_readme_documenta_el_comando_unico_y_los_comandos_de_demo():
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "cp .env.example .env" in readme
    assert "docker compose up --build" in readme
    assert "manage.py cargar_ejemplos" in readme
    assert "manage.py evaluar_dataset" in readme
