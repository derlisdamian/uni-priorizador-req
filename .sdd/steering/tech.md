# Stack Tecnológico

> MVP de hackatón (proyecto greenfield). Actualizado 2026-10-23: UI en Django y PostgreSQL, todo dockerizado para ejecución local.

## Arquitectura

Aplicación web Django con un **núcleo de dominio independiente del framework**, ejecutada con Docker Compose (servicios `web` y `db`):

```
Entrada (formulario / texto) → Vista Django → Evaluador IA (Gemini) → Evaluación por criterio (JSON validado)
   → Motor de reglas (pesos + umbrales + escalamiento) → Prioridad + Justificación → ORM Django (PostgreSQL) → Bandeja
```

- El **evaluador** (IA) solo produce datos estructurados; nunca decide la prioridad final.
- El **motor de reglas** es puro y determinístico: misma entrada → misma salida. Es la pieza más testeada.
- **Django es la capa de entrega y persistencia**: vistas, templates, formularios, ORM y admin. El paquete de dominio `triage/` no importa Django; las vistas traducen entre modelos ORM y modelos de dominio.
- La evaluación con IA se ejecuta **sincrónicamente en la request** (objetivo < 10 s). Sin colas ni workers en el MVP.

## Tecnologías Centrales

- **Lenguaje**: Python 3.12+
- **Framework web / UI**: Django 5.2 LTS con templates renderizados en servidor (formulario de pedido, bandeja, detalle con justificación, corrección manual). CSS liviano sin build (p. ej. Pico.css o Bootstrap por CDN); sin SPA.
- **Base de datos**: PostgreSQL 17 (imagen oficial `postgres:17`), acceso vía ORM de Django con `psycopg` 3
- **Contenedores**: Docker + Docker Compose para correr app y base de datos localmente
- **IA**: Google Gemini vía SDK `google-genai` (≥ 1.55, Interactions API) con salida estructurada por JSON Schema generado desde Pydantic
  - Modelo por defecto: `gemini-3.8-flash` (estable; mejor razonamiento de la línea Flash)
  - Modelo rápido/económico: `gemini-3.5-flash-lite` (respaldo ante límites de cuota o latencia)
  - El modelo se elige por configuración (`GEMINI_MODEL`), nunca hardcodeado

## Librerías Clave

- `django`: web, ORM, migraciones, admin
- `psycopg[binary]` 3: driver de PostgreSQL
- `django-environ` (o `os.environ`): settings desde variables de entorno
- `pydantic` v2: modelos de dominio y validación de la respuesta de la IA
- `google-genai`: cliente de Gemini (no usar el paquete legado `google-generativeai`)
- `pyyaml`: configuración de pesos/umbrales/tipos
- `pytest` + `pytest-django`: tests

## Contenedores (Docker Compose)

- **`db`**: PostgreSQL con volumen nombrado para persistir datos y `healthcheck` (`pg_isready`).
- **`web`**: imagen propia basada en `python:3.12-slim`; dependencias instaladas con `uv`; código montado como volumen para recarga en caliente; `depends_on: db` con `condition: service_healthy`.
- Al arrancar, `web` aplica migraciones y levanta `runserver 0.0.0.0:8000` (entorno local; no se requiere gunicorn para la demo).
- La app se conecta a la base por el nombre de servicio (`db`), nunca a `localhost`.
- Datos de ejemplo cargables con un comando de gestión (`manage.py cargar_ejemplos`) o fixtures.

## Estándares de Desarrollo

### Tipado y Validación
- Type hints en todo el código; modelos Pydantic en los bordes del dominio (respuesta de IA, entrada al motor de reglas).
- Formularios Django validan la entrada del usuario; las vistas convierten a modelos de dominio antes de llamar a `triage/`.
- Toda respuesta de la IA se valida con `Modelo.model_validate_json(...)`; si falla → reintento único → respaldo por palabras clave + "Requiere revisión".
- Gemini no garantiza restricciones de rango/longitud del schema: validar en Pydantic (p. ej. puntajes 0–3) y mantener el schema plano y pequeño (schemas muy anidados son rechazados con `400 INVALID_ARGUMENT`).

### Persistencia
- Todo cambio de esquema mediante migraciones de Django versionadas.
- La evaluación completa de la IA (puntajes, evidencia, confianza) se guarda en un campo `JSONField` además de los campos consultables (prioridad, tipo, puntaje, estado).
- Las correcciones manuales se registran como entidad propia (quién, cuándo, valor anterior, valor nuevo, motivo); nunca se sobrescribe la recomendación original.

### Configuración
- Pesos, umbrales, reglas y tipos viven en `config/*.yaml`, no hardcodeados.
- Secretos y conexión solo por variables de entorno vía `.env` no versionado (`GEMINI_API_KEY`, `GEMINI_MODEL`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`); incluir `.env.example` sin valores reales.

### Calidad
- `ruff` para lint/format.
- Prompts versionados como archivos de texto, no strings dispersos en el código.

### Testing
- Motor de reglas: tests unitarios exhaustivos (umbrales, escalamientos, bordes), sin Django ni base de datos.
- Evaluador: tests con respuestas de IA simuladas (sin llamadas reales a Gemini).
- Vistas/modelos: `pytest-django` contra el PostgreSQL del contenedor.
- Dataset etiquetado (`data/`): comando de evaluación que reporta % de aciertos de prioridad y tipo.

## Entorno de Desarrollo

### Herramientas
- Docker Desktop (o Docker Engine) con Compose v2
- Python 3.12+ y `uv` solo si se desarrolla fuera del contenedor

### Comandos Comunes
```bash
# Levantar:     docker compose up --build
# Migraciones:  docker compose exec web python manage.py migrate
# Superusuario: docker compose exec web python manage.py createsuperuser
# Datos demo:   docker compose exec web python manage.py cargar_ejemplos
# Tests:        docker compose exec web pytest
# Evaluar:      docker compose exec web python manage.py evaluar_dataset data/pedidos_ejemplo.json
# Bajar:        docker compose down        (agregar -v para borrar la base)
```

## Decisiones Técnicas Clave

- **IA evalúa, regla decide**: explicabilidad y control institucional por encima de "caja negra".
- **Django sobre Streamlit**: formularios, ORM, migraciones y admin listos de fábrica; el admin sirve como panel de corrección y datos sin código extra. El núcleo `triage/` desacoplado mantiene la lógica testeable sin el framework.
- **PostgreSQL dockerizado**: mismo motor que un despliegue institucional real, `JSONField` nativo para la evaluación de la IA y cero instalación local más allá de Docker.
- **Docker Compose local**: cualquier integrante del equipo (y el jurado) levanta todo con un solo comando.
- **Sincrónico en el MVP**: una llamada a Gemini por pedido no justifica Celery/Redis en una hackatón.
- **Respaldo sin IA**: la demo no puede depender al 100 % de la red/API.
- **Gemini como proveedor, detrás de una interfaz**: el dominio depende de un protocolo `EvaluadorPedidos`; `GeminiEvaluador` es una implementación y el respaldo por palabras clave es otra. Cambiar de proveedor no toca el motor de reglas.
- **Cuota y privacidad**: el nivel gratuito de Gemini tiene límites de solicitudes por minuto y puede usar los datos para mejorar sus productos. Para la demo: cachear resultados del dataset de ejemplo y no enviar datos personales (nombres, teléfonos) en el prompt.

---
_Documentar estándares y patrones, no cada dependencia_
