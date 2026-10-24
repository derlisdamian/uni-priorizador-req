"""Caché de evaluaciones: permite repetir la demo y el dataset sin consultar a Gemini."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from triage.evaluadores import EvaluadorPedidos
from triage.schemas import EntradaEvaluacion, EvaluacionCriterios


class EvaluadorCacheable(EvaluadorPedidos, Protocol):
    """Un evaluador que identifica su modelo y su prompt, que forman parte de la clave."""

    modelo: str

    @property
    def version_prompt(self) -> str: ...


class EvaluadorConCache:
    """Decora otro evaluador y guarda sus evaluaciones en un archivo JSON versionable.

    La clave combina el modelo, la versión del prompt y la entrada enviada (el texto y los
    datos informados), así que cambiar el modelo o el prompt invalida las entradas previas.
    """

    def __init__(self, interno: EvaluadorCacheable, archivo: Path):
        self.interno = interno
        self.archivo = Path(archivo)
        self._entradas: dict[str, dict] = (
            json.loads(self.archivo.read_text(encoding="utf-8")) if self.archivo.exists() else {}
        )

    @property
    def nombre(self) -> str:
        return f"cache+{self.interno.nombre}"

    @property
    def modelo(self) -> str:
        return self.interno.modelo

    @property
    def version_prompt(self) -> str:
        return self.interno.version_prompt

    def _clave(self, entrada: EntradaEvaluacion) -> str:
        identidad = [self.modelo, self.version_prompt, entrada.model_dump(mode="json")]
        serializada = json.dumps(identidad, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serializada.encode("utf-8")).hexdigest()

    def evaluar(self, entrada: EntradaEvaluacion) -> EvaluacionCriterios:
        clave = self._clave(entrada)
        if clave in self._entradas:
            return EvaluacionCriterios.model_validate(self._entradas[clave])
        evaluacion = self.interno.evaluar(entrada)
        entradas = self._entradas | {clave: evaluacion.model_dump(mode="json")}
        self._guardar(entradas)
        self._entradas = entradas
        return evaluacion

    def _guardar(self, entradas: dict[str, dict]) -> None:
        """Escritura atómica: archivo temporal en el mismo directorio y luego rename."""
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        contenido = json.dumps(entradas, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        descriptor, temporal = tempfile.mkstemp(
            dir=self.archivo.parent, prefix=f".{self.archivo.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as salida:
                salida.write(contenido)
            os.replace(temporal, self.archivo)
        except BaseException:
            Path(temporal).unlink(missing_ok=True)
            raise


def envolver_con_cache(
    evaluador: EvaluadorCacheable, *, usar_cache: bool, archivo: Path
) -> EvaluadorPedidos:
    """Aplica el caché solo si está activado por configuración (`TRIAGE_USAR_CACHE`)."""
    return EvaluadorConCache(evaluador, archivo) if usar_cache else evaluador
