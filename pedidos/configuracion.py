"""Configuración de triage del proceso: se carga una sola vez al arrancar (requisito 10.2)."""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from triage.config import ConfiguracionInvalida, ConfiguracionTriage, cargar_configuracion

_actual: ConfiguracionTriage | None = None
_error: ConfiguracionInvalida | None = None


def inicializar(directorio: Path, *, estricto: bool = True) -> None:
    """Carga y valida la configuración; los cambios en los YAML se aplican al reiniciar.

    Con `estricto`, una configuración inválida lanza `ImproperlyConfigured` e impide el
    arranque (requisito 10.3). Sin él, el error se conserva y lo relanza `obtener()`.
    """
    global _actual, _error
    try:
        _actual, _error = cargar_configuracion(directorio), None
    except ConfiguracionInvalida as error:
        _actual, _error = None, error
        if estricto:
            raise ImproperlyConfigured(str(error)) from error


def obtener() -> ConfiguracionTriage:
    if _actual is None:
        raise ImproperlyConfigured(str(_error) if _error else "La configuración no se cargó.")
    return _actual
