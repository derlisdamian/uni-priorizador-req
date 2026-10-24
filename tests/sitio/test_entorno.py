"""El archivo de ejemplo documenta el entorno sin exponer secretos."""

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CLAVES_REQUERIDAS = {
    "DJANGO_SECRET_KEY",
    "DJANGO_DEBUG",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT_S",
    "TRIAGE_USAR_CACHE",
    "TRIAGE_CONFIG_DIR",
}
CLAVES_SECRETAS = {"DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "GEMINI_API_KEY"}


def leer_env_example() -> dict[str, str]:
    variables = {}
    for linea in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#"):
            clave, _, valor = linea.partition("=")
            variables[clave.strip()] = valor.strip()
    return variables


def test_env_example_lista_todas_las_variables():
    assert CLAVES_REQUERIDAS <= leer_env_example().keys()


def test_env_example_no_tiene_secretos_reales():
    variables = leer_env_example()
    for clave in CLAVES_SECRETAS:
        assert variables[clave] == "", f"{clave} no debe tener valor en .env.example"


def test_env_real_excluido_del_repositorio():
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignorados
