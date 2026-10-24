"""Validación de las evaluaciones recibidas de un evaluador (requisitos 3.1, 3.2, 3.3 y 3.5)."""

from triage.config import ConfiguracionTriage
from triage.schemas import EvaluacionCriterios, PuntajeCriterio
from triage.texto import normalizar_texto

PUNTAJE_CON_EVIDENCIA = 2  # desde este puntaje, el criterio exige evidencia literal


class EvaluacionInvalida(Exception):
    def __init__(self, motivos: list[str]):
        self.motivos = motivos
        super().__init__("Evaluación inválida: " + "; ".join(motivos))


def _validar_tipos(candidata: EvaluacionCriterios, config: ConfiguracionTriage) -> list[str]:
    tipos = config.nombres_tipos()
    motivos = [
        f"tipo desconocido «{tipo}»"
        for tipo in [candidata.tipo_principal, *candidata.tipos_secundarios]
        if tipo not in tipos
    ]
    if candidata.tipo_principal in candidata.tipos_secundarios:
        motivos.append(f"el tipo principal «{candidata.tipo_principal}» se repite como secundario")
    return motivos


def _puntaje_valido(puntaje: object) -> bool:
    return type(puntaje) is int and 0 <= puntaje <= 3


def _validar_criterios(candidata: EvaluacionCriterios, config: ConfiguracionTriage) -> list[str]:
    claves = config.claves_criterios()
    motivos = [f"falta el criterio «{c}»" for c in claves if c not in candidata.criterios]
    motivos += [f"criterio desconocido «{c}»" for c in candidata.criterios if c not in claves]
    motivos += [
        f"el puntaje de «{c}» debe ser un entero entre 0 y 3 ({p.puntaje!r})"
        for c, p in candidata.criterios.items()
        if c in claves and not _puntaje_valido(p.puntaje)
    ]
    return motivos


def _depurar_evidencia(
    criterios: dict[str, PuntajeCriterio], texto_enviado: str
) -> tuple[dict[str, PuntajeCriterio], list[str]]:
    """Descarta los fragmentos que no aparecen en el texto enviado."""
    texto = normalizar_texto(texto_enviado)
    depurados: dict[str, PuntajeCriterio] = {}
    motivos = []
    for clave, criterio in criterios.items():
        evidencia = [
            fragmento
            for fragmento in criterio.evidencia
            if (normalizado := normalizar_texto(fragmento)) and normalizado in texto
        ]
        if criterio.puntaje >= PUNTAJE_CON_EVIDENCIA and not evidencia:
            motivos.append(
                f"el criterio «{clave}» tiene puntaje {criterio.puntaje} "
                "sin evidencia que aparezca en el texto"
            )
        depurados[clave] = criterio.model_copy(update={"evidencia": evidencia})
    return depurados, motivos


def validar_evaluacion(
    candidata: EvaluacionCriterios, texto_enviado: str, config: ConfiguracionTriage
) -> EvaluacionCriterios:
    """Devuelve una copia con la evidencia depurada o lanza `EvaluacionInvalida`."""
    motivos = _validar_tipos(candidata, config)
    errores_criterios = _validar_criterios(candidata, config)
    motivos += errores_criterios
    criterios = candidata.criterios
    if not errores_criterios:
        criterios, sin_evidencia = _depurar_evidencia(candidata.criterios, texto_enviado)
        motivos += sin_evidencia
    if not candidata.descripcion_normalizada.strip():
        motivos.append("la descripción normalizada está vacía")
    if motivos:
        raise EvaluacionInvalida(motivos)
    return candidata.model_copy(update={"criterios": criterios})
