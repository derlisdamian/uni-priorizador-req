# Estructura del Proyecto

> Proyecto greenfield: estas son las convenciones a seguir al crear el código.

## Filosofía de Organización

**Por capas, con el dominio en el centro.** El paquete `triage/` contiene toda la lógica de negocio y no importa nada de la UI. La UI (`app/`) y los scripts dependen del dominio, nunca al revés.

```
app/  ──►  triage/  ◄──  scripts / evaluación
             │
             └─► config/ (YAML)
```

## Patrones de Directorios

### Dominio
**Ubicación**: `triage/`
**Propósito**: modelos, motor de reglas, extractor IA, clasificación de respaldo, repositorio de persistencia.
**Ejemplo**: `triage/scoring.py` (motor puro de puntaje y escalamiento), `triage/extractor.py` (llamada al LLM + validación), `triage/models.py` (Pydantic).

### Prompts
**Ubicación**: `triage/prompts/`
**Propósito**: plantillas de prompt versionadas en texto plano.
**Ejemplo**: `triage/prompts/evaluar_pedido.md`

### Interfaz
**Ubicación**: `app/`
**Propósito**: páginas Streamlit; solo presentación y orquestación de llamadas al dominio.
**Ejemplo**: `app/main.py`, `app/pages/bandeja.py`, `app/pages/nuevo_pedido.py`

### Configuración
**Ubicación**: `config/`
**Propósito**: pesos, umbrales, reglas de escalamiento y tipos de pedido.
**Ejemplo**: `config/criterios.yaml`, `config/tipos.yaml`

### Datos de ejemplo
**Ubicación**: `data/`
**Propósito**: pedidos de muestra etiquetados para demo y evaluación.
**Ejemplo**: `data/pedidos_ejemplo.json`

### Tests
**Ubicación**: `tests/` (espeja la estructura de `triage/`)
**Ejemplo**: `tests/test_scoring.py`

## Convenciones de Nombres

- **Archivos/módulos**: `snake_case.py`
- **Clases / modelos**: `PascalCase` (`Pedido`, `EvaluacionCriterios`, `ResultadoTriage`)
- **Funciones y variables**: `snake_case`
- **Vocabulario de dominio en español** (pedido, prioridad, criterio, dependencia); términos técnicos genéricos pueden quedar en inglés.
- **Claves de criterios**: las definidas en `triage-criteria.md` (`riesgo_personas`, `seguridad`, …), idénticas en YAML, modelos y prompts.

## Organización de Imports

```python
# Absolutos desde la raíz del paquete
from triage.models import Pedido, ResultadoTriage
from triage.scoring import calcular_prioridad
```

- Sin imports relativos entre capas.
- `app/` puede importar `triage`; `triage` nunca importa `app` ni `streamlit`.

## Principios de Organización del Código

- **Funciones puras en el motor de reglas**: reciben evaluación + configuración, devuelven resultado; sin I/O.
- **Bordes validados**: todo lo que entra (usuario, IA, archivos) pasa por un modelo Pydantic.
- **Un único punto de acceso a la IA** (`extractor`), fácil de simular en tests.

---
_Documentar patrones, no árboles de archivos. Archivos nuevos que siguen el patrón no requieren actualizar este documento_
