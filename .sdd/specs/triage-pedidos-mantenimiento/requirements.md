# Requirements Document

## Project Description (Input)
Sistema de triage institucional de pedidos de mantenimiento

## Introducción

El **Sistema de Triage** recibe pedidos de mantenimiento, reparaciones y pequeñas obras enviados por las dependencias de la universidad, ya sea mediante un formulario web o pegando el texto libre de un correo o nota. Un evaluador de IA interpreta cada pedido (ubicación, descripción normalizada, tipo y puntaje por criterio con evidencia textual) y un motor de reglas determinístico calcula la prioridad P1–P4 a partir de criterios ponderados, umbrales y reglas de escalamiento configurables. El responsable de mantenimiento (triador) trabaja sobre una bandeja ordenada por prioridad, consulta la justificación de cada resultado y puede corregir prioridad y tipo dejando registro del motivo.

El alcance corresponde al MVP de hackatón definido en el steering: quedan fuera la autenticación real y los roles, la integración con el correo institucional, las notificaciones, los adjuntos o fotos, la asignación de cuadrillas y la gestión completa de órdenes de trabajo.

**Convenciones de este documento**
- *Criterios*: `riesgo_personas`, `seguridad`, `interrupcion_servicios`, `impacto_academico`, `usuarios_afectados`, `deterioro_progresivo`, `urgencia_temporal`, `accesibilidad`, `costo_estimado`, con escala 0–3 (ver `triage-criteria.md`).
- *Tipos de pedido*: Electricidad, Sanitaria, Cubierta, Climatización, Accesibilidad, Mobiliario, Infraestructura, TIC, Seguridad.
- *Estados del pedido*: **Pendiente** (priorizado por el sistema, sin validar), **Requiere revisión** (el sistema no tiene suficiente certeza) y **Validado** (confirmado o corregido por el triador).
- Los valores numéricos de pesos, umbrales y confianza mínima mencionados son los valores iniciales de la configuración y pueden modificarse sin cambiar el código.

## Requirements

### Requirement 1: Registro de pedidos mediante formulario
**Objective:** Como solicitante de una dependencia, quiero reportar un problema completando un formulario simple, para que mi pedido ingrese al circuito de mantenimiento sin trámites adicionales.

#### Acceptance Criteria
1. The Sistema de Triage shall ofrecer un formulario web con los campos dependencia solicitante, ubicación (edificio, piso o espacio), descripción del problema en lenguaje natural y datos de contacto opcionales.
2. When el solicitante envía el formulario con la descripción completa, the Sistema de Triage shall registrar el pedido con su fecha y hora de recepción y el canal "formulario".
3. If el solicitante envía el formulario sin descripción del problema o sin dependencia, the Sistema de Triage shall rechazar el envío e indicar qué campos faltan, conservando los datos ya ingresados.
4. When un pedido queda registrado, the Sistema de Triage shall iniciar su interpretación automática y su priorización sin intervención adicional del solicitante.
5. When la priorización de un pedido recién registrado finaliza, the Sistema de Triage shall mostrar el identificador del pedido, la prioridad recomendada, el tipo detectado y la justificación.

### Requirement 2: Ingesta de texto libre (correo o nota)
**Objective:** Como responsable de mantenimiento, quiero pegar el texto de un correo o nota tal como llegó, para que los pedidos que ingresan por otros canales reciban el mismo tratamiento que los del formulario.

#### Acceptance Criteria
1. The Sistema de Triage shall ofrecer una opción para pegar texto libre como un pedido, con un campo opcional para indicar la dependencia.
2. When se envía un texto libre no vacío, the Sistema de Triage shall registrar el pedido con el texto original íntegro, su fecha y hora de recepción y el canal "texto libre".
3. When un pedido de texto libre se interpreta, the Sistema de Triage shall extraer del texto la dependencia y la ubicación cuando estén presentes.
4. If la dependencia o la ubicación no pueden determinarse ni a partir del texto ni de los datos ingresados, the Sistema de Triage shall registrar esos datos como "no informado" y marcar el pedido como "Requiere revisión".
5. If se envía un texto libre vacío o compuesto solo por espacios, the Sistema de Triage shall rechazar el envío e informar el motivo.

### Requirement 3: Interpretación automática del pedido
**Objective:** Como responsable de mantenimiento, quiero que el sistema interprete cada pedido y puntúe cada criterio con evidencia del texto, para no tener que leer y clasificar manualmente cada solicitud.

#### Acceptance Criteria
1. When un pedido se interpreta, the Sistema de Triage shall producir una descripción normalizada del problema, la ubicación, un tipo principal y, opcionalmente, tipos secundarios, todos pertenecientes a la lista de tipos configurada.
2. When un pedido se interpreta, the Sistema de Triage shall asignar a cada criterio configurado un puntaje entero entre 0 y 3.
3. When un criterio recibe un puntaje mayor o igual a 2, the Sistema de Triage shall asociarle al menos un fragmento textual del pedido original que lo justifique.
4. When un pedido se interpreta, the Sistema de Triage shall registrar un nivel de confianza entre 0 y 1 para la clasificación.
5. If el resultado de la interpretación contiene un tipo fuera de la lista configurada, un puntaje fuera del rango 0–3 o datos faltantes, the Sistema de Triage shall descartar ese resultado y tratarlo como una interpretación fallida.
6. The Sistema de Triage shall conservar el texto original del pedido sin modificaciones, independientemente de la descripción normalizada generada.
7. The Sistema de Triage shall completar la interpretación y la priorización de un pedido en menos de 10 segundos en condiciones normales de disponibilidad del servicio de IA.

### Requirement 4: Cálculo determinístico de la prioridad
**Objective:** Como responsable de mantenimiento, quiero que la prioridad surja de una regla institucional fija aplicada a los puntajes, para que el mismo problema reciba la misma prioridad sin importar quién lo redacte.

#### Acceptance Criteria
1. When se dispone de los puntajes por criterio de un pedido, the Sistema de Triage shall calcular el puntaje total como la suma de (peso del criterio × puntaje del criterio / 3), en un rango de 0 a 100.
2. When se calcula el puntaje total, the Sistema de Triage shall asignar la prioridad por umbral: P1 si el puntaje es mayor o igual a 70, P2 si está entre 45 y 69, P3 si está entre 20 y 44, y P4 si es menor a 20.
3. If `riesgo_personas` o `seguridad` tienen puntaje 3, the Sistema de Triage shall asignar prioridad P1.
4. If `accesibilidad` tiene puntaje 3, the Sistema de Triage shall asignar como mínimo prioridad P2.
5. If `interrupcion_servicios` tiene puntaje 3 y `usuarios_afectados` tiene puntaje mayor o igual a 2, the Sistema de Triage shall asignar como mínimo prioridad P2.
6. The Sistema de Triage shall aplicar las reglas de escalamiento solo para elevar la prioridad obtenida por umbral, nunca para reducirla.
7. The Sistema de Triage shall excluir `costo_estimado` del aumento de prioridad, utilizándolo solo como dato informativo.
8. The Sistema de Triage shall producir siempre el mismo puntaje total y la misma prioridad para los mismos puntajes por criterio y la misma configuración.

### Requirement 5: Justificación explicable
**Objective:** Como responsable de mantenimiento, quiero ver por qué cada pedido recibió su prioridad, para poder confiar en la recomendación o detectar rápidamente cuándo corregirla.

#### Acceptance Criteria
1. The Sistema de Triage shall acompañar toda prioridad recomendada con una justificación que incluya la prioridad, el puntaje total, la prioridad que correspondía por umbral, el tipo detectado y las reglas de escalamiento aplicadas.
2. The Sistema de Triage shall incluir en la justificación cada criterio con puntaje mayor o igual a 2, junto con su puntaje y la evidencia textual asociada.
3. When una regla de escalamiento modifica la prioridad, the Sistema de Triage shall indicar en la justificación la prioridad por umbral, la prioridad final y la regla que produjo el cambio.
4. The Sistema de Triage shall redactar la justificación en lenguaje legible por personas no técnicas, en español.
5. When el resultado proviene de la clasificación de respaldo, the Sistema de Triage shall indicarlo explícitamente en la justificación.

### Requirement 6: Revisión requerida y funcionamiento sin IA
**Objective:** Como responsable de mantenimiento, quiero que el sistema señale los casos dudosos y siga funcionando aunque la IA no esté disponible, para no perder pedidos ni confiar ciegamente en resultados inciertos.

#### Acceptance Criteria
1. If la confianza de la clasificación es menor a 0.6, the Sistema de Triage shall marcar el pedido como "Requiere revisión".
2. If el texto del pedido es insuficiente para evaluar los criterios o existe conflicto entre tipos candidatos, the Sistema de Triage shall marcar el pedido como "Requiere revisión" e indicar el motivo.
3. If la interpretación automática falla, the Sistema de Triage shall reintentarla una única vez.
4. If el servicio de IA no está disponible o la interpretación falla tras el reintento, the Sistema de Triage shall clasificar el pedido mediante un procedimiento de respaldo basado en palabras clave por tipo, calcular su prioridad con el mismo motor de reglas y marcarlo como "Requiere revisión".
5. The Sistema de Triage shall registrar todo pedido recibido aunque fallen tanto la interpretación automática como la clasificación de respaldo, dejándolo en estado "Requiere revisión".
6. The Sistema de Triage shall identificar en cada resultado si fue obtenido por la IA o por la clasificación de respaldo.

### Requirement 7: Bandeja de triage
**Objective:** Como responsable de mantenimiento, quiero una bandeja ordenada por urgencia y con filtros, para atender primero lo crítico y encontrar pedidos rápidamente.

#### Acceptance Criteria
1. The Sistema de Triage shall mostrar una bandeja con todos los pedidos registrados, indicando para cada uno identificador, fecha de recepción, dependencia, ubicación, tipo principal, prioridad, puntaje total y estado.
2. The Sistema de Triage shall ordenar la bandeja por prioridad vigente (P1 primero), luego por puntaje total descendente y luego por fecha de recepción ascendente.
3. When el triador aplica un filtro por tipo, dependencia, prioridad o estado, the Sistema de Triage shall mostrar solo los pedidos que cumplen todos los filtros aplicados, manteniendo el orden definido.
4. The Sistema de Triage shall distinguir visualmente los pedidos en estado "Requiere revisión" y los pedidos con prioridad P1.
5. While un pedido tiene una corrección manual vigente, the Sistema de Triage shall mostrar en la bandeja la prioridad y el tipo corregidos e indicar que fueron corregidos.
6. If ningún pedido cumple los filtros aplicados, the Sistema de Triage shall mostrar un mensaje indicando que no hay resultados.

### Requirement 8: Detalle del pedido
**Objective:** Como responsable de mantenimiento, quiero consultar toda la información de un pedido en una sola vista, para decidir si confirmo o corrijo la recomendación.

#### Acceptance Criteria
1. When el triador selecciona un pedido en la bandeja, the Sistema de Triage shall mostrar el texto original, la descripción normalizada, la dependencia, la ubicación, el canal, la fecha de recepción, los tipos detectados y el estado.
2. When se muestra el detalle de un pedido, the Sistema de Triage shall mostrar los puntajes de todos los criterios, la confianza, el origen del resultado (IA o respaldo) y la justificación completa.
3. While un pedido tiene correcciones manuales, the Sistema de Triage shall mostrar en el detalle tanto la recomendación original como el historial de correcciones.

### Requirement 9: Validación y corrección manual
**Objective:** Como responsable de mantenimiento, quiero confirmar o corregir la prioridad y el tipo de un pedido dejando constancia del motivo, para mantener el control humano y la trazabilidad de las decisiones.

#### Acceptance Criteria
1. When el triador confirma la recomendación de un pedido, the Sistema de Triage shall cambiar su estado a "Validado" sin modificar la prioridad ni el tipo.
2. When el triador corrige la prioridad o el tipo principal de un pedido indicando un motivo, the Sistema de Triage shall registrar la corrección con fecha y hora, responsable, valor anterior, valor nuevo y motivo, y cambiar el estado del pedido a "Validado".
3. If el triador intenta guardar una corrección sin motivo, the Sistema de Triage shall rechazarla e indicar que el motivo es obligatorio.
4. The Sistema de Triage shall conservar la recomendación original del sistema sin sobrescribirla cuando se registra una corrección.
5. When se registra más de una corrección sobre un mismo pedido, the Sistema de Triage shall considerar vigente la más reciente y conservar todas en el historial.
6. The Sistema de Triage shall restringir los valores de corrección a los niveles P1–P4 y a los tipos de la lista configurada.

### Requirement 10: Configuración de criterios y tipos
**Objective:** Como responsable institucional del criterio de priorización, quiero ajustar pesos, umbrales, reglas y tipos sin modificar el código, para adaptar la política de triage a las decisiones de la universidad.

#### Acceptance Criteria
1. The Sistema de Triage shall obtener los pesos de los criterios, los umbrales de prioridad, las reglas de escalamiento, el umbral de confianza mínima y la lista de tipos con sus señales desde una configuración externa al código.
2. When se modifica la configuración y se reinicia el sistema, the Sistema de Triage shall aplicar los nuevos valores a los pedidos que se prioricen a partir de ese momento.
3. If la configuración es inválida (criterios desconocidos, pesos negativos, umbrales no ordenados o puntajes fuera de 0–3 en las reglas), the Sistema de Triage shall impedir su uso e informar el error de configuración.
4. The Sistema de Triage shall mantener sin cambios las prioridades ya registradas cuando se modifica la configuración.

### Requirement 11: Dataset de ejemplo y medición de aciertos
**Objective:** Como equipo de la hackatón, quiero cargar pedidos de ejemplo etiquetados y medir los aciertos del sistema, para demostrar su funcionamiento y su calidad ante el jurado.

#### Acceptance Criteria
1. The Sistema de Triage shall incluir un dataset de entre 15 y 20 pedidos de ejemplo, cada uno con su prioridad y tipo principal esperados según etiquetado manual, que cubra todos los niveles P1–P4 y la mayoría de los tipos configurados.
2. When se solicita la carga de los ejemplos, the Sistema de Triage shall registrar y priorizar los pedidos del dataset para que aparezcan en la bandeja.
3. When se ejecuta la evaluación sobre el dataset, the Sistema de Triage shall informar el porcentaje de coincidencia de prioridad, el porcentaje de coincidencia de tipo principal, el tiempo de clasificación por pedido y el detalle de los casos no coincidentes.
4. Where existen resultados previamente almacenados para los pedidos del dataset, the Sistema de Triage shall poder reutilizarlos en la demo sin volver a consultar el servicio de IA.

### Requirement 12: Privacidad, operación y presentación
**Objective:** Como institución, quiero que el sistema proteja los datos personales y pueda ponerse en marcha de forma simple, para usarlo en la demo sin riesgos ni configuraciones complejas.

#### Acceptance Criteria
1. The Sistema de Triage shall excluir los datos de contacto ingresados en el formulario (nombres, teléfonos, correos) de la información enviada al servicio de IA.
2. The Sistema de Triage shall mantener las credenciales del servicio de IA y de la base de datos fuera del código fuente y del repositorio.
3. The Sistema de Triage shall poder ponerse en marcha localmente, junto con su base de datos, mediante un único comando documentado.
4. The Sistema de Triage shall presentar todas las pantallas y mensajes al usuario en español.
5. The Sistema de Triage shall conservar los pedidos, resultados y correcciones registrados entre reinicios del sistema.
