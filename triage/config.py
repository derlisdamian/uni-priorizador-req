"""Carga y validación de la política institucional de triage desde YAML."""

import hashlib
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictInt, ValidationError

from triage.schemas import Prioridad

ARCHIVO_CRITERIOS = "criterios.yaml"
ARCHIVO_TIPOS = "tipos.yaml"
SUMA_PESOS = 100
PRIORIDADES_CON_UMBRAL = (Prioridad.P1, Prioridad.P2, Prioridad.P3)  # P4 es el resto


def _prioridad_por_nombre(valor: Any) -> Any:
    """Acepta "P1"…"P4" en el YAML además del valor numérico."""
    if isinstance(valor, str) and valor in Prioridad.__members__:
        return Prioridad[valor]
    return valor


PrioridadYaml = Annotated[Prioridad, BeforeValidator(_prioridad_por_nombre)]


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SenalRespaldo(_Modelo):
    frase: str
    puntaje: StrictInt


class DefinicionCriterio(_Modelo):
    clave: str
    nombre: str
    peso: StrictInt
    informativo: bool = False
    senales_respaldo: list[SenalRespaldo] = []


class Umbral(_Modelo):
    prioridad: Prioridad
    minimo: int  # puntaje total mínimo (0–100) para alcanzar esta prioridad


class Condicion(_Modelo):
    criterio: str
    operador: Literal["igual", "mayor_o_igual"]
    valor: StrictInt


class ReglaEscalamiento(_Modelo):
    """Se cumple si se cumplen todas sus condiciones (Y)."""

    id: str
    descripcion: str
    condiciones: list[Condicion]
    prioridad_minima: PrioridadYaml


class DefinicionTipo(_Modelo):
    nombre: str
    senales: list[str] = []


class ConfiguracionTriage(_Modelo):
    criterios: list[DefinicionCriterio]
    umbrales: list[Umbral]  # P1, P2 y P3, en ese orden
    reglas: list[ReglaEscalamiento]
    confianza_minima: float
    tipos: list[DefinicionTipo]
    version: str  # sha256 corto del contenido de los YAML

    def claves_criterios(self) -> list[str]:
        return [c.clave for c in self.criterios]

    def nombres_tipos(self) -> list[str]:
        return [t.nombre for t in self.tipos]


class ConfiguracionInvalida(Exception):
    def __init__(self, errores: list[str]):
        self.errores = errores
        detalle = "\n".join(f"- {e}" for e in errores)
        super().__init__(f"Configuración de triage inválida:\n{detalle}")


class _ArchivoCriterios(_Modelo):
    criterios: list[DefinicionCriterio]
    umbrales: dict[str, int]
    reglas: list[ReglaEscalamiento]
    confianza_minima: float


class _ArchivoTipos(_Modelo):
    tipos: list[DefinicionTipo]


_MENSAJES_PYDANTIC = {
    "missing": "campo obligatorio",
    "extra_forbidden": "campo desconocido",
    "int_type": "debe ser un número entero",
    "int_parsing": "debe ser un número entero",
    "int_from_float": "debe ser un número entero",
    "float_type": "debe ser un número",
    "float_parsing": "debe ser un número",
    "string_type": "debe ser un texto",
    "bool_type": "debe ser verdadero o falso",
    "bool_parsing": "debe ser verdadero o falso",
    "list_type": "debe ser una lista",
    "dict_type": "debe ser un mapa",
    "model_type": "debe ser un mapa",
    "literal_error": "valor no permitido",
    "enum": "valor no permitido (se espera P1, P2, P3 o P4)",
}


def _errores_pydantic(archivo: str, error: ValidationError) -> list[str]:
    errores = []
    for detalle in error.errors():
        ubicacion = ".".join(str(parte) for parte in detalle["loc"])
        mensaje = _MENSAJES_PYDANTIC.get(detalle["type"], detalle["msg"])
        errores.append(f"{archivo}: {ubicacion}: {mensaje}")
    return errores


def _leer_yaml[M: BaseModel](
    directorio: Path, archivo: str, modelo: type[M], errores: list[str]
) -> tuple[M | None, bytes]:
    ruta = directorio / archivo
    try:
        contenido = ruta.read_bytes()
    except OSError:
        errores.append(f"{archivo}: no se encontró el archivo en {directorio}")
        return None, b""
    try:
        datos = yaml.safe_load(contenido)
    except yaml.YAMLError as error:
        errores.append(f"{archivo}: YAML mal formado ({error})")
        return None, contenido
    try:
        return modelo.model_validate(datos), contenido
    except ValidationError as error:
        errores.extend(_errores_pydantic(archivo, error))
        return None, contenido


def _fuera_de_escala(valor: int) -> bool:
    return not 0 <= valor <= 3


def _validar_criterios(criterios: list[DefinicionCriterio]) -> list[str]:
    errores = []
    vistos: set[str] = set()
    for c in criterios:
        if c.clave in vistos:
            errores.append(f"criterio duplicado: {c.clave}")
        vistos.add(c.clave)
        if c.peso < 0:
            errores.append(f"criterio {c.clave}: peso negativo ({c.peso})")
        if c.informativo and c.peso != 0:
            errores.append(f"criterio {c.clave}: es informativo y debe tener peso 0 ({c.peso})")
        for s in c.senales_respaldo:
            if _fuera_de_escala(s.puntaje):
                errores.append(
                    f"criterio {c.clave}: la señal «{s.frase}» tiene puntaje {s.puntaje}, "
                    "fuera de 0–3"
                )
    suma = sum(c.peso for c in criterios)
    if suma != SUMA_PESOS:
        errores.append(f"los pesos suman {suma} y deben sumar {SUMA_PESOS}")
    return errores


def _validar_umbrales(umbrales: dict[str, int]) -> list[str]:
    esperados = [p.name for p in PRIORIDADES_CON_UMBRAL]
    if sorted(umbrales) != esperados:
        return [f"umbrales: se esperan exactamente {', '.join(esperados)} ({sorted(umbrales)})"]
    errores = [
        f"umbrales: {nombre} = {minimo} está fuera de 0–100"
        for nombre, minimo in umbrales.items()
        if not 0 <= minimo <= 100
    ]
    valores = [umbrales[nombre] for nombre in esperados]
    if any(mayor <= menor for mayor, menor in zip(valores, valores[1:], strict=False)):
        errores.append(
            "umbrales: deben ser estrictamente decrecientes de P1 a P3 "
            f"(P1 = {valores[0]}, P2 = {valores[1]}, P3 = {valores[2]})"
        )
    return errores


def _validar_reglas(
    reglas: list[ReglaEscalamiento], criterios: list[DefinicionCriterio]
) -> list[str]:
    errores = []
    por_clave = {c.clave: c for c in criterios}
    ids: set[str] = set()
    for regla in reglas:
        if regla.id in ids:
            errores.append(f"regla duplicada: {regla.id}")
        ids.add(regla.id)
        if not regla.condiciones:
            errores.append(f"regla {regla.id}: no tiene condiciones (debe tener al menos una)")
        for cond in regla.condiciones:
            definicion = por_clave.get(cond.criterio)
            if definicion is None:
                errores.append(f"regla {regla.id}: criterio desconocido «{cond.criterio}»")
            elif definicion.informativo:
                errores.append(
                    f"regla {regla.id}: el criterio {cond.criterio} es informativo "
                    "y no puede usarse en reglas"
                )
            if _fuera_de_escala(cond.valor):
                errores.append(
                    f"regla {regla.id}: el valor {cond.valor} de {cond.criterio} está fuera de 0–3"
                )
    return errores


def _validar_tipos(tipos: list[DefinicionTipo]) -> list[str]:
    if not tipos:
        return ["tipos: la lista de tipos está vacía"]
    errores = []
    vistos: set[str] = set()
    for posicion, tipo in enumerate(tipos, start=1):
        nombre = tipo.nombre.strip()
        if not nombre:
            errores.append(f"tipos: el tipo {posicion} tiene el nombre vacío")
            continue
        if nombre.casefold() in vistos:
            errores.append(f"tipos: tipo duplicado «{nombre}»")
        vistos.add(nombre.casefold())
    return errores


def cargar_configuracion(directorio: Path) -> ConfiguracionTriage:
    """Carga `criterios.yaml` y `tipos.yaml`.

    Lanza `ConfiguracionInvalida` enumerando todos los errores encontrados.
    """
    directorio = Path(directorio)
    errores: list[str] = []
    archivo_criterios, bytes_criterios = _leer_yaml(
        directorio, ARCHIVO_CRITERIOS, _ArchivoCriterios, errores
    )
    archivo_tipos, bytes_tipos = _leer_yaml(directorio, ARCHIVO_TIPOS, _ArchivoTipos, errores)

    if archivo_criterios is not None:
        errores += _validar_criterios(archivo_criterios.criterios)
        errores += _validar_umbrales(archivo_criterios.umbrales)
        errores += _validar_reglas(archivo_criterios.reglas, archivo_criterios.criterios)
        if not 0.0 <= archivo_criterios.confianza_minima <= 1.0:
            errores.append(
                f"confianza_minima: {archivo_criterios.confianza_minima} está fuera de 0–1"
            )
    if archivo_tipos is not None:
        errores += _validar_tipos(archivo_tipos.tipos)

    if errores:
        raise ConfiguracionInvalida(errores)

    version = hashlib.sha256(bytes_criterios + b"\0" + bytes_tipos).hexdigest()[:12]
    return ConfiguracionTriage(
        criterios=archivo_criterios.criterios,
        umbrales=[
            Umbral(prioridad=p, minimo=archivo_criterios.umbrales[p.name])
            for p in PRIORIDADES_CON_UMBRAL
        ],
        reglas=archivo_criterios.reglas,
        confianza_minima=archivo_criterios.confianza_minima,
        tipos=archivo_tipos.tipos,
        version=version,
    )
