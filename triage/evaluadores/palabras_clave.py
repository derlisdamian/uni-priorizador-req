"""Evaluador de respaldo sin IA: señales de tipos y frases de respaldo de la configuración."""

import re

from triage.config import ConfiguracionTriage, DefinicionCriterio
from triage.evaluadores import ErrorEvaluacion, TipoErrorEvaluacion
from triage.schemas import EntradaEvaluacion, EvaluacionCriterios, PuntajeCriterio
from triage.texto import normalizar_texto

LARGO_DESCRIPCION = 200
MAX_EVIDENCIA = 3


def _aparece(frase: str, texto_normalizado: str) -> bool:
    """La frase aparece como palabras completas («red» no coincide dentro de «pared»)."""
    patron = rf"(?<!\w){re.escape(normalizar_texto(frase))}(?!\w)"
    return re.search(patron, texto_normalizado) is not None


class EvaluadorPalabrasClave:
    def __init__(self, config: ConfiguracionTriage):
        self.config = config

    @property
    def nombre(self) -> str:
        return "palabras_clave"

    def _puntuar(self, criterio: DefinicionCriterio, texto: str) -> PuntajeCriterio:
        encontradas = [s for s in criterio.senales_respaldo if _aparece(s.frase, texto)]
        if not encontradas:
            return PuntajeCriterio(puntaje=0, evidencia=[])
        puntaje = max(s.puntaje for s in encontradas)
        evidencia = [s.frase for s in encontradas if s.puntaje == puntaje][:MAX_EVIDENCIA]
        return PuntajeCriterio(puntaje=puntaje, evidencia=evidencia)

    def evaluar(self, entrada: EntradaEvaluacion) -> EvaluacionCriterios:
        texto = normalizar_texto(entrada.texto)
        coincidencias = {
            tipo.nombre: sum(_aparece(senal, texto) for senal in tipo.senales)
            for tipo in self.config.tipos
        }
        detectados = [nombre for nombre, cantidad in coincidencias.items() if cantidad > 0]
        if not detectados:
            raise ErrorEvaluacion(
                TipoErrorEvaluacion.SIN_COINCIDENCIAS,
                "el texto no contiene señales de ningún tipo configurado",
            )
        # max() devuelve el primero en caso de empate: gana el orden de la configuración.
        principal = max(detectados, key=coincidencias.__getitem__)
        empatados = [n for n in detectados if coincidencias[n] == coincidencias[principal]]

        return EvaluacionCriterios(
            descripcion_normalizada=" ".join(entrada.texto.split())[:LARGO_DESCRIPCION],
            dependencia=entrada.dependencia_informada,
            ubicacion=entrada.ubicacion_informada,
            tipo_principal=principal,
            tipos_secundarios=[n for n in detectados if n != principal],
            criterios={c.clave: self._puntuar(c, texto) for c in self.config.criterios},
            confianza=0.0,
            texto_insuficiente=False,
            conflicto_tipos=len(empatados) > 1,
        )
