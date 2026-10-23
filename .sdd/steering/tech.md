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
- **IA**: Google Gemini vía SDK `google-genai` (≥ 1.55, Interactions API) con salida estructurada por JSON Schema generado desde Pydantic
  - Modelo por defecto: `gemini-3.8-flash` (estable; mejor razonamiento de la línea Flash)
  - Modelo rápido/económico: `gemini-3.5-flash-lite` (respaldo ante límites de cuota o latencia)
  - El modelo se elige por configuración (`GEMINI_MODEL`), nunca hardcodeado
- **Persistencia**: SQLite (archivo local)

## Librerías Clave

- `pydantic` v2: modelos de dominio y validación de la respuesta de la IA
- `google-genai`: cliente de Gemini (no usar el paquete legado `google-generativeai`)
- `sqlmodel`: persistencia sobre SQLite reutilizando los modelos Pydantic
- `pyyaml`: configuración de pesos/umbrales/tipos
- `pytest`: tests

## Estándares de Desarrollo

### Tipado y Validación
- Type hints en todo el código; modelos Pydantic en los bordes (entrada de usuario, respuesta de IA).
- Toda respuesta de la IA se valida con `Modelo.model_validate_json(...)`; si falla → reintento único → respaldo por palabras clave + "Requiere revisión".
- Gemini no garantiza restricciones de rango/longitud del schema: validar en Pydantic (p. ej. puntajes 0–3) y mantener el schema plano y pequeño (schemas muy anidados son rechazados con `400 INVALID_ARGUMENT`).

### Configuración
- Pesos, umbrales, reglas y tipos viven en `config/*.yaml`, no hardcodeados.
- Secretos solo por variables de entorno (`GEMINI_API_KEY`, `GEMINI_MODEL`) vía `.env` no versionado; incluir `.env.example` sin valores.

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
- **Gemini como proveedor, detrás de una interfaz**: el dominio depende de un protocolo `EvaluadorPedidos`; `GeminiEvaluador` es una implementación y el respaldo por palabras clave es otra. Cambiar de proveedor no toca el motor de reglas.
- **Cuota y privacidad**: el nivel gratuito de Gemini tiene límites de solicitudes por minuto y puede usar los datos para mejorar sus productos. Para la demo: cachear resultados del dataset de ejemplo y no enviar datos personales (nombres, teléfonos) en el prompt.

---
_Documentar estándares y patrones, no cada dependencia_
