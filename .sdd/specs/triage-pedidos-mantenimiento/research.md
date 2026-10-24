# Investigación y Decisiones de Diseño

## Resumen
- **Feature**: `triage-pedidos-mantenimiento`
- **Alcance del descubrimiento**: Funcionalidad nueva (greenfield) con integración externa (Google Gemini) → descubrimiento completo.
- **Hallazgos clave**:
  - La salida estructurada de Gemini se pide con la Interactions API (`client.interactions.create(..., response_format={"type": "text", "mime_type": "application/json", "schema": ...})`) y se valida del lado del cliente con `Modelo.model_validate_json(interaction.output_text)`. Gemini hace cumplir `enum`, `minimum`/`maximum` y `minItems`/`maxItems`, pero descarta en silencio `minLength`/`maxLength` y otras restricciones. Los schemas con mucha ramificación se rechazan con `400 INVALID_ARGUMENT`.
  - La Interactions API **guarda las solicitudes del lado del servidor por defecto** (1 día en el nivel gratuito, 55 días en el pago). Para cumplir el requisito 12.1 y la política de privacidad del steering se envía `store=False` y no se incluyen los datos de contacto en la entrada.
  - Google ya no publica un límite fijo de RPM para el nivel gratuito. Los límites dependen del proyecto, y desde abril de 2026 se redujeron entre un 50 % y un 80 %. Por eso la demo no puede depender de la API: hacen falta el caché versionado del dataset y el respaldo por palabras clave.

## Registro de Investigación

### Salida estructurada con `google-genai` (Interactions API)
- **Contexto**: los requisitos 3.1 a 3.5 y 3.8 exigen una respuesta tipada y validada, y el steering define el SDK `google-genai` ≥ 1.55 con la Interactions API.
- **Fuentes consultadas**: documentación de salida estructurada de Gemini, documentación del SDK `python-genai` y documentación de la Interactions API (ver Referencias).
- **Hallazgos**:
  - El patrón documentado es `response_format` con `schema = Modelo.model_json_schema()`, más `model_validate_json` sobre `output_text`.
  - Se hacen cumplir `enum`, `minimum`, `maximum`, `minItems` y `maxItems`. Se ignoran `minLength`, `maxLength`, `uniqueItems` y `minProperties`.
  - Producen `400 INVALID_ARGUMENT` los schemas con `maxItems` grandes en arreglos anidados, los enums largos, las secuencias largas de propiedades opcionales y los `anyOf` con muchas alternativas.
  - `system_instruction` y `generation_config` (temperatura) se pasan en cada interacción.
  - Los errores del servicio llegan como `google.genai.errors.APIError`, con los atributos `code` y `message`. Las subclases `ClientError` (4xx) y `ServerError` (5xx) permiten distinguir la causa.
  - El timeout se configura con `types.HttpOptions` al crear el cliente.
- **Implicancias**:
  - El schema de respuesta se mantiene plano: un objeto `criterios` con 9 propiedades fijas `{puntaje, evidencia}`, `evidencia` con `maxItems: 3`, tipos como `enum` y ningún `anyOf` salvo los nulos indispensables.
  - Aunque Gemini hace cumplir los rangos, igual se validan en Pydantic: el steering lo exige y la validación es defensa en profundidad.
  - Hay que corregir el steering (`tech.md`), que dice que "Gemini no garantiza restricciones de rango". La documentación actual indica que `minimum`/`maximum` sí se hacen cumplir y que solo se descartan las restricciones de longitud.
  - Se usa temperatura 0 para reducir la variabilidad. El determinismo de la prioridad no depende de esto, porque lo garantiza el motor de reglas.

### Almacenamiento del lado del servidor y privacidad
- **Contexto**: requisitos 12.1 y 12.2.
- **Hallazgos**: con `store=False` la interacción no se guarda. No usamos el estado conversacional (`previous_interaction_id`) porque cada pedido es una consulta independiente.
- **Implicancias**:
  - El adaptador Gemini envía siempre `store=False`.
  - `EntradaEvaluacion` no tiene campo de contacto, lo que garantiza estructuralmente la exclusión del requisito 12.1.
  - El texto libre se anonimiza con un mejor esfuerzo: los correos y teléfonos se reemplazan con expresiones regulares antes de enviarse.

### Modelos, cuota y latencia
- **Contexto**: requisitos 3.7 (< 10 s) y 3.8 (modelo configurable), y 11.4 (demo sin IA).
- **Hallazgos**:
  - `gemini-3.8-flash` y `gemini-3.5-flash-lite` tienen acceso en el nivel gratuito.
  - Los modelos Pro son de pago desde abril de 2026.
  - Los límites de cuota se ven por proyecto en AI Studio.
- **Implicancias**:
  - `GEMINI_MODEL` se toma de una variable de entorno.
  - Cada intento tiene un timeout de 4 s, configurable con `GEMINI_TIMEOUT_S`. El peor caso es 2 intentos más el respaldo: ≈ 8,1 s, dentro del presupuesto de 10 s.
  - Se desactivan los reintentos automáticos del SDK, porque el requisito 6.3 pide exactamente un reintento y ese reintento lo controla el dominio.

### Django 5.2 LTS + PostgreSQL 17
- **Contexto**: capa de entrega y persistencia (steering).
- **Hallazgos**:
  - Django 5.2 es LTS, con soporte hasta abril de 2028.
  - `JSONField` es nativo en PostgreSQL.
  - `select_for_update` sirve para serializar las correcciones concurrentes.
  - `AppConfig.ready()` es el punto de carga temprana de la configuración.
- **Implicancias**: la configuración YAML se carga y se valida en `PedidosConfig.ready()`. Si es inválida, se lanza `ImproperlyConfigured` y el proceso no arranca (requisito 10.3).

## Evaluación de Patrones de Arquitectura

| Opción | Descripción | Fortalezas | Riesgos / Limitaciones | Notas |
|---|---|---|---|---|
| **Hexagonal liviana (seleccionada)** | El dominio `triage/` define puertos (`EvaluadorPedidos`, `AlmacenCache`); Gemini, el respaldo y el caché son adaptadores; Django es el adaptador de entrega y persistencia | Motor testeable sin framework; cambiar de proveedor de IA no toca las reglas | Requiere traducir entre schemas y modelos ORM | Coincide con `structure.md` ("dominio en el centro") |
| Django "fat models" | La lógica de priorización vive en los modelos ORM | Menos código | Acopla las reglas a la base y dificulta los tests puros | Contradice el steering |
| Pipeline asíncrono (Celery) | Evaluación en un worker | Desacopla la latencia | Infraestructura extra (Redis) y complejidad | Descartado en `tech.md` para el MVP |

## Decisiones de Diseño

### Decisión: el orquestador de triage vive en el dominio
- **Contexto**: la secuencia IA → reintento → respaldo → motor → justificación (requisitos 3, 4, 5 y 6) es lógica de negocio.
- **Alternativas consideradas**:
  1. Orquestar en `pedidos/services.py`.
  2. Orquestar en `triage/pipeline.py`, con los evaluadores inyectados.
- **Enfoque seleccionado**: opción 2. `pedidos/services.py` solo construye la entrada, llama a `triar_pedido` y persiste el resultado.
- **Fundamento**: permite testear sin Django todas las ramas de fallo y la evaluación del dataset (requisito 11.3), que reutiliza el mismo pipeline.
- **Compromisos**: el dominio conoce la política de reintento, lo cual es aceptable porque es una regla del requisito 6.3.

### Decisión: el respaldo por palabras clave también puntúa criterios
- **Contexto**: el requisito 6.4 exige calcular la prioridad "con el mismo motor de reglas", y el motor necesita puntajes por criterio.
- **Alternativas consideradas**:
  1. Respaldo solo de tipo, con prioridad fija P3.
  2. Señales por criterio en la configuración (`senales_respaldo`), que asignan puntajes con frases como evidencia.
- **Enfoque seleccionado**: opción 2. Los criterios sin señales reciben 0. La confianza del respaldo se fija en 0.0 y el resultado siempre lleva "Requiere revisión".
- **Fundamento**: con señales como "cables expuestos" → `riesgo_personas = 3`, el escalamiento a P1 sigue funcionando sin IA.
- **Compromisos**: la precisión es baja, pero queda mitigada por la revisión obligatoria.

### Decisión: el caché guarda la evaluación, no la prioridad
- **Contexto**: requisitos 11.4, 4.8 y 10.2.
- **Enfoque seleccionado**: el decorador `EvaluadorConCache` guarda `EvaluacionCriterios` en `data/cache/evaluaciones.json`, versionado en el repositorio. La clave es `sha256(texto anonimizado + modelo + versión del prompt)`. El motor siempre recalcula la prioridad.
- **Fundamento**: si cambian los pesos, la demo refleja la nueva configuración sin volver a llamar a Gemini.
- **Compromisos**: si cambia el prompt se invalida el caché, por lo que hay que regenerarlo con `evaluar_dataset --refrescar-cache`.

### Decisión: aritmética entera en el motor
- **Contexto**: el requisito 4.8 exige determinismo y el 4.2 umbrales exactos ("entre 45 y 69").
- **Enfoque seleccionado**:
  - Los pesos son enteros y la configuración exige que sumen 100.
  - Se calcula `suma3 = Σ peso × puntaje`, un entero entre 0 y 300.
  - La comparación es `suma3 ≥ 3 × umbral`.
  - `puntaje_total = suma3 / 3` se guarda como `Decimal` con 2 decimales y se muestra con 1.
- **Fundamento**: se evitan los errores de coma flotante en los bordes. Por ejemplo, un total de 69,67 cae en P2 y uno de 70,00 en P1.

### Decisión: el escalamiento es solo una "prioridad mínima"
- **Contexto**: requisitos 4.3 a 4.6. "Forzar P1" equivale a "mínimo P1".
- **Enfoque seleccionado**: cada regla es `{id, descripcion, condiciones: [{criterio, operador: igual|mayor_o_igual, valor}], prioridad_minima}`. Las condiciones de una regla se combinan con Y. Un "O" se expresa con dos reglas.
- **Fundamento**: un solo efecto es monótono por construcción, lo que cumple el requisito 4.6.

### Decisión: los pedidos sin clasificación tienen prioridad nula
- **Contexto**: el requisito 6.5 cubre el caso en que fallan la IA y el respaldo.
- **Enfoque seleccionado**:
  - El pedido queda con `prioridad_vigente = NULL`, en estado "Requiere revisión" y con el motivo `sin_clasificacion`.
  - En la bandeja se ordena al final (`NULLS LAST`), con un aviso "N pedidos sin clasificar" visible arriba.
- **Fundamento**: inventar una prioridad sería engañoso. Ubicarlo antes que los P1 contradiría el requisito 7.2.
- **Seguimiento**: confirmar con el equipo si se prefiere que aparezcan al principio.

## Riesgos y Mitigaciones
- **La IA devuelve evidencia parafraseada en lugar de literal.** Mitigación: se compara con normalización (minúsculas, sin acentos, espacios colapsados). Los fragmentos que no aparecen se descartan. Solo se invalida el resultado si un criterio con puntaje ≥ 2 queda sin ninguna evidencia, lo que dispara el reintento.
- **Límites de cuota (429) durante la demo.** Mitigación: caché versionado del dataset, respaldo por palabras clave y cambio a `gemini-3.5-flash-lite` modificando solo `GEMINI_MODEL`.
- **Latencia mayor a 10 s.** Mitigación: timeout de 4 s por intento, sin reintentos del SDK y medición de `duracion_ms` en cada resultado.
- **Configuración YAML editada a mano con errores.** Mitigación: validación estricta con Pydantic al arrancar y el comando `validar_config`.
- **Correcciones concurrentes sobre el mismo pedido.** Mitigación: `select_for_update` dentro de una transacción.

## Paralelización (para la fase de tareas)
- **Independientes entre sí**, porque solo dependen de `triage/schemas.py` y `triage/config.py`: el motor de reglas (`scoring.py`), la justificación, el evaluador Gemini, el evaluador por palabras clave y el caché.
- **Primero**: `schemas.py` y `config.py` junto con los YAML, porque definen los contratos compartidos.
- **Después del pipeline**: los modelos ORM y las migraciones. Las vistas y templates dependen de los servicios.
- **En paralelo con todo**: Docker y Compose.
- **Requiere el pipeline completo**: el dataset de ejemplo y su evaluación.

## Referencias
- [Gemini API — Structured outputs](https://ai.google.dev/gemini-api/docs/structured-output): patrón `response_format` y restricciones de schema soportadas.
- [Gemini API — Interactions](https://ai.google.dev/gemini-api/docs/interactions): `store=False`, retención y parámetros por interacción.
- [python-genai SDK](https://googleapis.github.io/python-genai/): `HttpOptions` y `errors.APIError`.
- [Gemini API pricing 2026](https://geotoolbox.ai/blog/gemini-api-pricing): cambios de cuota del nivel gratuito (abril de 2026).
- [Agentdeals — cambios de precios de Gemini](https://agentdeals.dev/gemini-api-pricing-changes): recortes de límites del nivel gratuito.
- Steering interno: `tech.md`, `structure.md` y `triage-criteria.md`.
