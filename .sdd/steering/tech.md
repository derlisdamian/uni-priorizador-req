# Stack Tecnológico

> Propuesta inicial para el MVP de hackatón (proyecto greenfield). Confirmar con el equipo antes de la fase de Diseño.

## Arquitectura

Monolito Python con un **núcleo de dominio independiente de la UI**:

```
Entrada (formulario / texto) → Extractor IA → Evaluación por criterio (JSON validado)
   → Motor de reglas (pesos + umbrales + escalamiento) → Prioridad + Justificación → Persistencia → Bandeja
```

- El **extractor** (IA) solo produce datos estructurados; nunca decide la prioridad final.
- El **motor de reglas** es puro y determinístico: misma entrada → misma salida. Es la pieza más testeada.
- La **UI** consume el núcleo; reemplazar Streamlit por una API/SPA no debe tocar el dominio.

## Tecnologías Centrales

- **Lenguaje**: Python 3.12+
- **UI**: Streamlit (formulario, bandeja, detalle con justificación) — máxima velocidad para la demo
- **IA**: Anthropic SDK con modelos Claude (`claude-sonnet-5-5` por defecto; `claude-haiku-4-5-20251001` si se prioriza velocidad/costo), salida estructurada vía *tool use* / JSON schema
- **Persistencia**: SQLite (archivo local)

## Librerías Clave

- `pydantic` v2: modelos de dominio y validación de la respuesta de la IA
- `anthropic`: cliente del LLM
- `sqlmodel` o `sqlite3`: persistencia simple
- `pyyaml`: configuración de pesos/umbrales/tipos
- `pytest`: tests

## Estándares de Desarrollo

### Tipado y Validación
- Type hints en todo el código; modelos Pydantic en los bordes (entrada de usuario, respuesta de IA).
- Toda respuesta de la IA se valida contra el schema; si falla → reintento único → respaldo por palabras clave + "Requiere revisión".

### Configuración
- Pesos, umbrales, reglas y tipos viven en `config/*.yaml`, no hardcodeados.
- Secretos solo por variables de entorno (`ANTHROPIC_API_KEY`) vía `.env` no versionado.

### Calidad
- `ruff` para lint/format.
- Prompts versionados como archivos de texto, no strings dispersos en el código.

### Testing
- Motor de reglas: tests unitarios exhaustivos (umbrales, escalamientos, bordes).
- Extractor: tests con respuestas de IA simuladas (sin llamadas reales en CI).
- Dataset etiquetado (`data/`): script de evaluación que reporta % de aciertos de prioridad y tipo.

## Entorno de Desarrollo

### Herramientas
- Python 3.12+, `uv` (o `pip` + `venv`)

### Comandos Comunes
```bash
# Instalar: uv sync
# Ejecutar: uv run streamlit run app/main.py
# Tests:    uv run pytest
# Evaluar:  uv run python -m triage.evaluate data/pedidos_ejemplo.json
```

## Decisiones Técnicas Clave

- **IA evalúa, regla decide**: explicabilidad y control institucional por encima de "caja negra".
- **Streamlit sobre SPA**: el objetivo es una demo funcional en horas; el núcleo desacoplado permite migrar después.
- **SQLite**: cero infraestructura; suficiente para el volumen del MVP.
- **Respaldo sin IA**: la demo no puede depender al 100 % de la red/API.

---
_Documentar estándares y patrones, no cada dependencia_
