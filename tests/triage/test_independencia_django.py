"""El paquete de dominio `triage` no debe depender de Django."""

import ast
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PAQUETES_PROHIBIDOS = {"django", "pedidos", "sitio"}


def test_importar_triage_no_carga_django():
    codigo = "import sys, triage; print('django' in sys.modules)"
    salida = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=True,
    )
    assert salida.stdout.strip() == "False"


def test_ningun_modulo_de_triage_importa_django_ni_la_capa_web():
    for archivo in (RAIZ / "triage").rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                modulos = [alias.name for alias in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                modulos = [nodo.module]
            else:
                continue
            for modulo in modulos:
                assert modulo.split(".")[0] not in PAQUETES_PROHIBIDOS, (
                    f"{archivo.relative_to(RAIZ)} importa {modulo}"
                )
