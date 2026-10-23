# Criterios de Triage (Dominio)

Modelo de priorización del sistema. Es la fuente de verdad para el cálculo de P1–P4; los pesos y umbrales son **configurables** (archivo de configuración, no código) y los valores siguientes son la propuesta inicial a validar con el equipo.

## Principio

> La IA **evalúa** cada criterio con evidencia; una **regla determinística** decide la prioridad.

Esto garantiza reproducibilidad, auditabilidad y que un cambio de criterio institucional se haga ajustando pesos, no reentrenando ni reescribiendo prompts.

## Escala por Criterio (0–3)

| Puntaje | Significado |
|---|---|
| 0 | No aplica / sin impacto |
| 1 | Bajo |
| 2 | Medio |
| 3 | Alto / grave |

## Criterios y Pesos (propuesta)

| Criterio (`clave`) | Peso | Ejemplo de puntaje 3 |
|---|---|---|
| Riesgo para las personas (`riesgo_personas`) | 22 | Cables expuestos en pasillo, riesgo de caída de mampostería |
| Seguridad (`seguridad`) | 14 | Puerta de emergencia trabada, alarma de incendio fuera de servicio |
| Interrupción de servicios (`interrupcion_servicios`) | 12 | Sin agua/luz en todo un edificio, caída de red |
| Impacto en actividades académicas (`impacto_academico`) | 12 | Aula inutilizable con clases o exámenes programados |
| Cantidad de usuarios afectados (`usuarios_afectados`) | 10 | > 100 personas o un edificio completo |
| Riesgo de deterioro progresivo (`deterioro_progresivo`) | 10 | Filtración activa sobre tablero eléctrico o archivo |
| Urgencia temporal (`urgencia_temporal`) | 10 | Evento, examen o lluvia prevista en < 48 h |
| Accesibilidad (`accesibilidad`) | 10 | Ascensor/rampa único fuera de servicio |
| Costo estimado (`costo_estimado`) | 0 | Informativo: se usa para desempate y planificación, no para subir prioridad |

**Puntaje total** = Σ (peso × puntaje / 3) → rango 0–100.

## Umbrales

| Puntaje total | Prioridad |
|---|---|
| ≥ 70 | P1 |
| 45 – 69 | P2 |
| 20 – 44 | P3 |
| < 20 | P4 |

## Reglas de Escalamiento (se aplican después del puntaje)

- `riesgo_personas = 3` **o** `seguridad = 3` → **P1** forzado.
- `accesibilidad = 3` (sin alternativa de acceso) → mínimo **P2**.
- `interrupcion_servicios = 3` y `usuarios_afectados ≥ 2` → mínimo **P2**.
- Las reglas solo **elevan** prioridad, nunca la bajan.

## Confianza y Revisión Humana

- La IA devuelve una confianza (0–1) por clasificación.
- Confianza < 0.6, texto insuficiente o conflicto entre tipos → marcar **"Requiere revisión"**.
- Si la IA no está disponible: clasificación de respaldo por palabras clave + marca de revisión.

## Justificación (obligatoria)

Cada resultado incluye: prioridad, puntaje total, criterios con puntaje ≥ 2 y su evidencia textual, reglas de escalamiento aplicadas y tipo detectado. Ejemplo:

> **P1** (puntaje 63 → P2 por umbral, escalado a P1) — Regla: riesgo para las personas = 3. Evidencia: *"cables pelados en el pasillo del 2º piso"*. Tipo: Electricidad.

## Tipos y Señales de Ejemplo

| Tipo | Señales típicas |
|---|---|
| Electricidad | tablero, corto, enchufe, cables, sin luz |
| Sanitaria | pérdida de agua, baño, cañería, inodoro, cloaca |
| Cubierta | techo, goteras, filtración, membrana, canaleta |
| Climatización | aire acondicionado, calefacción, caldera, ventilación |
| Accesibilidad | rampa, ascensor, baño adaptado, barandas |
| Mobiliario | sillas, bancos, pizarrón, escritorio, armario |
| Infraestructura | paredes, pisos, puertas, ventanas, grietas, revoque |
| TIC | proyector, wifi, red, computadora, cámara |
| Seguridad | matafuegos, alarma, salida de emergencia, cerradura, iluminación de emergencia |

---
_Cambios a pesos/umbrales: actualizar aquí y en la configuración; registrar el motivo_
