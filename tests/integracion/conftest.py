"""Fixtures de los tests de integración."""

import pytest

from pedidos import configuracion
from triage.config import ConfiguracionTriage


@pytest.fixture
def config() -> ConfiguracionTriage:
    return configuracion.obtener()
