# Visión del Producto

**Priorizador inteligente de pedidos de obras y mantenimiento** — un sistema de *triage* institucional para la universidad. Recibe solicitudes de mantenimiento, reparaciones y pequeñas obras enviadas por las dependencias (formulario o texto de correo/nota), las interpreta automáticamente con IA, identifica el tipo de pedido y recomienda un nivel de prioridad P1–P4 con una justificación explicable.

Contexto: prototipo/MVP desarrollado en una hackatón (Desafío 7). Se prioriza una demo funcional, clara y explicable por sobre la completitud.

## Problema

Los pedidos llegan desde distintas dependencias, por distintos canales y con distinta redacción. No existe un criterio homogéneo para priorizarlos: la urgencia depende de quién escribe y cómo lo escribe, no del riesgo o impacto real.

## Usuarios

- **Solicitante** (dependencia, docente, personal administrativo): reporta un problema en lenguaje natural.
- **Responsable de mantenimiento / obras** (triador): revisa la bandeja priorizada, confirma o corrige la prioridad y el tipo.

## Capacidades Centrales

1. **Ingesta multicanal simple**: formulario web y pegado de texto libre (correo/nota). Otros canales (lectura de buzón, fotos) quedan fuera del MVP.
2. **Interpretación automática**: la IA extrae ubicación, descripción normalizada, tipo de pedido y una puntuación por criterio, con evidencia textual.
3. **Priorización determinística y explicable**: una matriz de criterios ponderados + reglas de escalamiento calcula P1–P4 (ver `triage-criteria.md`). La IA *evalúa*, la regla *decide*.
4. **Bandeja de triage**: lista ordenada por prioridad y puntaje, con filtros por tipo, dependencia y estado.
5. **Validación humana**: el triador puede corregir prioridad/tipo; la corrección y su motivo quedan registrados.

## Niveles de Prioridad

| Nivel | Significado | Respuesta orientativa |
|---|---|---|
| **P1** | Crítico / intervención inmediata | Mismo día (< 24 h) |
| **P2** | Alta prioridad | < 72 h |
| **P3** | Programable | Planificación semanal/mensual |
| **P4** | Mejora / no urgente | Backlog / plan anual |

## Tipos de Pedido

Electricidad · Sanitaria · Cubierta · Climatización · Accesibilidad · Mobiliario · Infraestructura · TIC · Seguridad.
Un pedido tiene un tipo principal y opcionalmente tipos secundarios.

## Propuesta de Valor

- **Criterio homogéneo**: el mismo problema recibe la misma prioridad sin importar quién lo redacte.
- **Explicabilidad**: cada prioridad muestra *por qué* (criterios, puntajes, reglas aplicadas, frases del texto).
- **Humano en el circuito**: la herramienta recomienda, no reemplaza al responsable.
- **Adopción inmediata**: acepta el texto tal como llega hoy, sin exigir formularios complejos.

## Alcance del MVP (Hackatón)

**Dentro**: formulario + texto pegado, clasificación de tipo, puntaje por criterio, P1–P4 con justificación, bandeja con filtros, corrección manual, dataset de ejemplo (15–20 pedidos) para demo y medición de aciertos.

**Fuera**: autenticación real/roles, integración con correo institucional, notificaciones, adjuntos/fotos, asignación de cuadrillas, gestión de órdenes de trabajo completa.

## Métricas de Éxito (demo)

- % de coincidencia de prioridad y tipo contra el dataset etiquetado manualmente.
- Tiempo de clasificación por pedido (objetivo: < 10 s).
- Cada resultado incluye justificación legible.

---
_Decisiones de producto: revisar al cerrar la fase de Requisitos_
