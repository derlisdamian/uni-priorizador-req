"""Los secretos viven solo en el `.env` no versionado (requisito 12.2)."""

import os
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SECRETOS = ["DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "GEMINI_API_KEY"]
# Lo que no se versiona (ver .gitignore) y no se revisa.
EXCLUIDOS = {".env", ".git", ".venv", ".idea", "__pycache__", ".pytest_cache", ".ruff_cache"}
API_KEY_GOOGLE = re.compile(r"AIza[0-9A-Za-z_-]{35}")


def archivos_versionables() -> list[Path]:
    return [
        ruta
        for ruta in RAIZ.rglob("*")
        if ruta.is_file() and not EXCLUIDOS & set(ruta.relative_to(RAIZ).parts)
    ]


def test_el_env_real_no_se_versiona():
    assert ".env" in (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_el_ejemplo_de_entorno_no_tiene_secretos():
    valores = dict(
        linea.split("=", 1)
        for linea in (RAIZ / ".env.example").read_text(encoding="utf-8").splitlines()
        if "=" in linea and not linea.startswith("#")
    )
    for nombre in SECRETOS:
        assert valores[nombre] == "", f"{nombre} tiene un valor en .env.example"


def test_ningun_archivo_contiene_una_api_key_de_google():
    for ruta in archivos_versionables():
        contenido = ruta.read_text(encoding="utf-8", errors="ignore")
        assert not API_KEY_GOOGLE.search(contenido), ruta.relative_to(RAIZ)


@pytest.mark.parametrize("nombre", SECRETOS)
def test_ningun_archivo_contiene_el_valor_real_del_secreto(nombre):
    valor = os.environ.get(nombre, "")
    if len(valor) < 8 or valor == "clave-solo-para-tests":
        pytest.skip(f"{nombre} no está definido en este entorno")
    for ruta in archivos_versionables():
        assert valor not in ruta.read_text(encoding="utf-8", errors="ignore"), ruta.relative_to(
            RAIZ
        )
