# Estructura del Proyecto

> Proyecto greenfield: estas son las convenciones a seguir al crear el código. Actualizado 2026-10-23: capa de entrega en Django + PostgreSQL con Docker Compose.

## Filosofía de Organización

**Por capas, con el dominio en el centro.** El paquete `triage/` contiene toda la lógica de negocio y **no importa Django**. La app Django (`pedidos/`) es la capa de entrega y persistencia: depende del dominio, nunca al revés.

```
sitio/ (settings, urls) ──► pedidos/ (vistas, forms, ORM, admin, comandos) ──► triage/ (dominio puro)
                                                                                   │
                                                                                   └─► config/ (YAML)
```

## Patrones de Directorios

### Dominio
**Ubicación**: `triage/`
**Propósito**: schemas Pydantic, motor de reglas, evaluadores (Gemini y respaldo por palabras clave), carga de configuración. Sin Django, sin base de datos, sin I/O web.
**Ejemplo**: `triage/scoring.py` (motor puro de puntaje y escalamiento), `triage/evaluadores/gemini.py` (llamada a Gemini + validación), `triage/evaluadores/palabras_clave.py` (respaldo), `triage/schemas.py` (Pydantic).

### Prompts
**Ubicación**: `triage/prompts/`
**Propósito**: plantillas de prompt versionadas en texto plano.
**Ejemplo**: `triage/prompts/evaluar_pedido.md`

### Proyecto Django
**Ubicación**: `sitio/`
**Propósito**: configuración del proyecto (`settings.py` leyendo variables de entorno, `urls.py` raíz, `wsgi.py`). Sin lógica de negocio.

### App Django
**Ubicación**: `pedidos/`
**Propósito**: modelos ORM (pedido, resultado de triage, corrección manual), formularios, vistas, URLs, admin y templates. Orquesta: valida entrada → convierte a schema de dominio → llama a `triage/` → persiste.
**Ejemplo**: `pedidos/models.py`, `pedidos/views.py`, `pedidos/forms.py`, `pedidos/admin.py`, `pedidos/templates/pedidos/bandeja.html`
**Comandos de gestión**: `pedidos/management/commands/` (p. ej. `cargar_ejemplos.py`, `evaluar_dataset.py`)

### Configuración de triage
**Ubicación**: `config/`
**Propósito**: pesos, umbrales, reglas de escalamiento y tipos de pedido.
**Ejemplo**: `config/criterios.yaml`, `config/tipos.yaml`

### Datos de ejemplo
**Ubicación**: `data/`
**Propósito**: pedidos de muestra etiquetados para demo y evaluación.
**Ejemplo**: `data/pedidos_ejemplo.json`

### Tests
**Ubicación**: `tests/`, separando `tests/triage/` (unitarios puros, sin base de datos) y `tests/pedidos/` (`pytest-django`, contra PostgreSQL del contenedor).
**Ejemplo**: `tests/triage/test_scoring.py`, `tests/pedidos/test_views.py`

### Raíz del repositorio
Archivos de infraestructura: `manage.py`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `.env.example`. El `.env` real nunca se versiona.

## Convenciones de Nombres

- **Archivos/módulos**: `snake_case.py`
- **Clases / modelos**: `PascalCase` (`Pedido`, `EvaluacionCriterios`, `ResultadoTriage`)
- **Funciones y variables**: `snake_case`
- **Vocabulario de dominio en español** (pedido, prioridad, criterio, dependencia); términos técnicos genéricos pueden quedar en inglés.
- **Claves de criterios**: las definidas en `triage-criteria.md` (`riesgo_personas`, `seguridad`, …), idénticas en YAML, schemas, modelos ORM y prompts.
- **Schemas vs modelos**: "schema" = Pydantic del dominio (`triage/schemas.py`); "model" = ORM de Django (`pedidos/models.py`). No mezclar.
- **URLs y templates**: nombres de URL con namespace `pedidos:` (`pedidos:bandeja`, `pedidos:detalle`); templates en `pedidos/templates/pedidos/`.

## Organización de Imports

```python
# Absolutos desde la raíz del repositorio
from triage.schemas import EvaluacionCriterios, ResultadoTriage
from triage.scoring import calcular_prioridad
from pedidos.models import Pedido
```

- Sin imports relativos entre capas.
- `pedidos/` puede importar `triage`; `triage` nunca importa `django`, `pedidos` ni `sitio`.

## Principios de Organización del Código

- **Funciones puras en el motor de reglas**: reciben evaluación + configuración, devuelven resultado; sin I/O.
- **Vistas delgadas**: la lógica de priorización vive en `triage/`; las vistas solo validan, delegan y persisten. Si una vista crece, extraer a `pedidos/services.py`.
- **Bordes validados**: entrada de usuario por formularios Django; respuestas de IA y datos hacia el motor por schemas Pydantic.
- **Un único punto de acceso a la IA** (protocolo `EvaluadorPedidos`), inyectable y fácil de simular en tests.

---
_Documentar patrones, no árboles de archivos. Archivos nuevos que siguen el patrón no requieren actualizar este documento_
