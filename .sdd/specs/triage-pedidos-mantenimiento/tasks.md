# Plan de Implementación

- [x] 1. Base del proyecto y entorno de ejecución
- [x] 1.1 Crear el esqueleto del proyecto Python y Django
  - Definir las dependencias del proyecto (Django, driver de PostgreSQL, Pydantic, PyYAML, cliente de Gemini, pytest, pytest-django, ruff), gestionadas con uv
  - Crear el proyecto Django y la app de pedidos, junto al paquete de dominio de triage, que no debe depender de Django
  - Leer de variables de entorno la clave secreta, el modo debug, la conexión a PostgreSQL (servicio `db`), la API key y el modelo de Gemini, el timeout, el uso de caché y el directorio de configuración
  - Configurar el idioma español y la zona horaria local para toda la interfaz
  - Proveer un archivo de ejemplo de variables de entorno sin valores reales y excluir del repositorio el archivo de entorno real
  - Configurar pytest, separando los tests puros de dominio de los tests con base de datos, y configurar ruff
  - _Requirements: 3.8, 12.2, 12.4_

- [x] 1.2 (P) Dockerizar la aplicación y la base de datos para levantarlas con un solo comando
  - Construir la imagen de la aplicación sobre Python 3.12 slim, con las dependencias instaladas por uv y el código montado para recarga en caliente
  - Definir el servicio de base de datos PostgreSQL 17 con un volumen nombrado y un healthcheck de disponibilidad
  - Hacer que la aplicación espere a que la base esté sana, aplique las migraciones y levante el servidor de desarrollo accesible desde el host
  - Dejar documentado el comando único de arranque y los comandos opcionales de demo
  - Se puede hacer en paralelo con 1.1 porque toca solo archivos de contenedores; para verificarlo hace falta el esqueleto de 1.1
  - _Requirements: 12.3, 12.5_

- [x] 2. Contratos de dominio y configuración de triage
- [x] 2.1 Definir los modelos de datos del dominio
  - Representar los niveles de prioridad P1–P4 de modo que el orden natural coincida con la urgencia
  - Representar el canal de ingreso, el origen del resultado (IA, respaldo o sin clasificación) y los motivos de revisión
  - Modelar la entrada que se envía al evaluador, sin ningún campo de datos de contacto
  - Modelar la evaluación por criterio (puntaje entero 0–3 y evidencia), con la descripción normalizada, la ubicación, la dependencia, los tipos, la confianza 0–1 y las banderas de texto insuficiente y conflicto de tipos
  - Modelar el cálculo de prioridad, la justificación y el resultado completo del triage, incluidos los intentos, los errores, la versión de configuración y la duración
  - Validar en el borde los rangos de puntajes y de confianza, y verificarlo con tests unitarios
  - _Requirements: 3.1, 3.2, 3.4, 6.6, 12.1_

- [x] 2.2 Cargar y validar la configuración institucional desde archivos YAML
  - Crear la configuración inicial: 9 criterios con nombre legible, peso, marca informativa y señales de respaldo; umbrales P1 = 70, P2 = 45 y P3 = 20; las 4 reglas de escalamiento; confianza mínima 0.6; los 9 tipos con sus señales
  - Expresar cada regla de escalamiento como un conjunto de condiciones combinadas con Y, con una prioridad mínima resultante
  - Rechazar la configuración, enumerando todos los errores encontrados, cuando haya:
    - criterios desconocidos;
    - pesos negativos o no enteros, o pesos que no suman 100;
    - un criterio informativo con peso o usado en una regla;
    - umbrales no decrecientes;
    - valores fuera de 0–3 en las reglas;
    - una confianza mínima fuera de rango;
    - tipos vacíos o duplicados
  - Calcular una versión corta de la configuración a partir del contenido de los archivos
  - Cubrir con tests cada caso de configuración inválida y la carga de la configuración inicial
  - _Requirements: 4.7, 10.1, 10.3_

- [x] 3. Lógica determinística de priorización
- [x] 3.1 (P) Implementar el motor de reglas de puntaje y prioridad
  - Calcular el puntaje total como la suma ponderada de los puntajes dividida por 3, usando aritmética entera para que los bordes de los umbrales sean exactos
  - Asignar la prioridad por umbral y aplicar las reglas de escalamiento solo para elevarla, nunca para reducirla
  - Informar las reglas aplicadas en el orden de la configuración, indicando cuál produjo el cambio
  - Rechazar puntajes con claves faltantes, claves desconocidas o valores fuera de rango
  - Testear los bordes de cada umbral (69,67 frente a 70; 44,67 frente a 45; 19,67 frente a 20), cada regla, que el costo estimado no tenga efecto, que las reglas sean monótonas y el determinismo
  - Requiere 2.1 y 2.2; es independiente de 3.2 y 3.3
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

- [x] 3.2 (P) Implementar la validación de las evaluaciones recibidas
  - Verificar que el tipo principal y los secundarios pertenezcan a la lista configurada, sin repetir el principal
  - Verificar que estén presentes todos los criterios, sin claves desconocidas y con puntajes enteros entre 0 y 3
  - Comparar cada fragmento de evidencia con el texto enviado, normalizando mayúsculas, acentos y espacios, y descartar los que no aparecen
  - Rechazar la evaluación si un criterio con puntaje mayor o igual a 2 queda sin evidencia, o si la descripción normalizada está vacía
  - Testear el tipo fuera de la lista, el puntaje fuera de rango, la evidencia faltante y la evidencia parafraseada
  - _Requirements: 3.1, 3.2, 3.3, 3.5_

- [x] 3.3 (P) Redactar la justificación legible en español
  - Componer un texto con la prioridad final, el puntaje total, la prioridad que correspondía por umbral y los tipos detectados
  - Listar cada criterio con puntaje mayor o igual a 2, con su nombre legible, su puntaje y la evidencia citada
  - Cuando una regla de escalamiento cambia la prioridad, explicar la prioridad por umbral, la prioridad final y la regla responsable
  - Anteponer un aviso explícito cuando el resultado proviene de la clasificación de respaldo, y generar un texto específico para los pedidos sin clasificación
  - Testear los casos con escalamiento, sin escalamiento, de respaldo y sin clasificación
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 4. Evaluadores de pedidos
- [x] 4.1 (P) Implementar el evaluador de respaldo por palabras clave
  - Detectar el tipo principal por la cantidad de señales encontradas en el texto normalizado, y tomar como secundarios los demás tipos con coincidencias
  - Resolver los empates por el orden de la configuración, marcando conflicto entre tipos
  - Puntuar los criterios con las frases de respaldo configuradas, usando la frase encontrada como evidencia y 0 para los criterios sin señales
  - Fijar la confianza en 0 e informar un error específico cuando no se detecta ningún tipo
  - Testear la detección, los empates, los puntajes por señal y la ausencia de coincidencias
  - _Requirements: 6.2, 6.4_

- [x] 4.2 (P) Implementar el evaluador con Gemini según el contrato REST generateContent
  - Crear el prompt versionado como archivo de texto, con la escala, los criterios, los tipos y sus señales, y la instrucción de citar evidencia literal y de extraer la dependencia y la ubicación del texto libre
  - Generar el schema de respuesta plano a partir de la configuración: tipos enumerados, puntajes 0–3, como máximo 3 fragmentos de evidencia y confianza 0–1
  - Llamar al endpoint `generateContent` con el modelo tomado de la configuración del entorno, la API key solo en el header, un único contenido sin historial, las instrucciones de sistema, temperatura 0 y salida JSON con schema
  - Aplicar el timeout configurado (4 s por defecto) y desactivar los reintentos automáticos del cliente
  - Leer la respuesta del primer candidato y tratar como respuesta inválida la falta de candidatos, un motivo de finalización distinto de STOP o un bloqueo
  - Traducir las fallas a errores de evaluación tipificados (no configurado, timeout, servicio o respuesta inválida), validando la respuesta con el validador de 3.2
  - Testear con un transporte simulado: la URL, el header, la forma del cuerpo, la ausencia de datos de contacto, la lectura de la respuesta y la traducción de errores
  - Requiere 3.2
  - _Requirements: 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 3.8, 12.1_

- [x] 4.3 (P) Implementar el caché de evaluaciones
  - Envolver a otro evaluador y reutilizar las evaluaciones guardadas, identificadas por el texto, el modelo y la versión del prompt
  - Persistir el caché en un archivo versionable en el repositorio, con escritura atómica
  - Activarlo o desactivarlo por configuración del entorno, manteniendo el origen "IA" cuando el resultado proviene del caché
  - Testear el acierto, el fallo y que se invalide cuando cambia el modelo o el prompt
  - _Requirements: 11.4_

- [ ] 5. Orquestar el triage con reintento, respaldo y revisión
  - Anonimizar los correos y teléfonos del texto antes de construir la entrada del evaluador
  - Ejecutar la evaluación principal, con un único reintento ante cualquier falla excepto la falta de configuración, que pasa directo al respaldo
  - Recurrir al evaluador de respaldo y, si tampoco clasifica, producir un resultado sin clasificación y sin prioridad
  - Calcular la prioridad con el motor y redactar la justificación para los resultados de IA y de respaldo
  - Determinar los motivos de revisión: confianza menor que la mínima, texto insuficiente, conflicto de tipos, dependencia o ubicación no informadas, y clasificación de respaldo
  - Medir la duración total, registrar los errores de cada intento, registrar la versión de configuración y garantizar que la orquestación nunca termine con una excepción
  - Testear con evaluadores simulados: éxito, éxito tras el reintento, respaldo, falta de configuración, sin clasificación, confianza 0,59 y que la entrada no contenga el contacto
  - _Requirements: 2.4, 3.5, 3.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 12.1_

- [ ] 6. Persistencia y casos de uso de la aplicación
- [ ] 6.1 (P) Crear los modelos de persistencia y sus migraciones
  - Persistir el pedido con:
    - el texto original inmutable;
    - el canal, la dependencia, la ubicación y el contacto;
    - la fecha de recepción, el estado y los motivos de revisión;
    - los valores vigentes desnormalizados (prioridad, tipo y puntaje), la marca de corregido y los datos de validación;
    - un código de ejemplo único
  - Persistir el resultado del triage en relación 1 a 1 y solo por inserción, con la evaluación completa en JSON, la justificación, la versión de configuración y la duración
  - Persistir las correcciones manuales solo por inserción, con fecha, responsable, valores anteriores y nuevos, y un motivo obligatorio también como restricción de la base
  - Agregar los índices para el orden y los filtros de la bandeja, y registrar los modelos en el admin, con resultados y correcciones de solo lectura
  - Requiere 1.1 y 2.1; es independiente de 3, 4 y 5
  - _Requirements: 3.6, 9.4, 9.5, 10.4, 12.5_

- [ ] 6.2 Cargar la configuración al iniciar la aplicación y exponer su validación
  - Cargar y validar la configuración una sola vez al arrancar y compartirla en todo el proceso
  - Impedir el arranque con un error de configuración que enumere los problemas
  - Ofrecer un comando que valide la configuración e informe la versión o los errores, con un código de salida distinto de cero si falla
  - Testear que una configuración inválida impide el uso y que los cambios se aplican tras reiniciar
  - Requiere 2.2 y 6.1
  - _Requirements: 10.2, 10.3_

- [ ] 6.3 Implementar el registro de pedidos con priorización automática
  - Construir los evaluadores a partir de la configuración del entorno (Gemini, con caché opcional, y respaldo), de forma inyectable para los tests
  - Guardar el pedido antes de evaluarlo, en estado "Requiere revisión", para que quede registrado aunque todo falle
  - Ejecutar el triage con el texto anonimizado y sin datos de contacto
  - Guardar el resultado y actualizar en una sola transacción los datos del pedido: la dependencia y la ubicación resueltas o "No informado", la prioridad, el tipo, el puntaje, el estado y los motivos
  - Registrar en el log cada triage sin incluir el texto, y advertir si se superan los 10 segundos
  - Testear el registro por formulario y por texto libre, la persistencia ante una excepción del triage y que no cambien las prioridades registradas al cambiar la configuración
  - Requiere 5, 6.1 y 6.2
  - _Requirements: 1.2, 1.4, 2.2, 2.4, 3.6, 3.7, 6.5, 10.4, 12.1_

- [ ] 6.4 Implementar la confirmación y la corrección manual
  - Confirmar un pedido cambiando su estado a "Validado" sin modificar la prioridad ni el tipo, y rechazar la confirmación de pedidos sin clasificación
  - Registrar las correcciones con fecha, responsable, valor anterior, valor nuevo y motivo, bloqueando el pedido durante la transacción
  - Actualizar la prioridad y el tipo vigentes, marcar el pedido como corregido y validado, y conservar intacta la recomendación original
  - Rechazar las correcciones sin motivo o sin responsable, con valores fuera de P1–P4 o de los tipos configurados, o sin ningún cambio
  - Testear el historial de varias correcciones, la vigencia de la más reciente y la inmutabilidad del resultado original
  - Requiere 6.3
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [ ] 6.5 (P) Implementar la consulta filtrada y ordenada de la bandeja
  - Filtrar por tipo, dependencia, prioridad y estado sobre los valores vigentes, combinando los filtros con Y
  - Ordenar por prioridad vigente (los pedidos sin prioridad al final), luego por puntaje total descendente y luego por fecha de recepción ascendente
  - Proveer las opciones de cada filtro desde la configuración y desde los valores registrados
  - Testear el orden y las combinaciones de filtros contra PostgreSQL
  - Requiere 6.1; es independiente de 6.3 y 6.4
  - _Requirements: 7.2, 7.3_

- [ ] 7. Interfaz web en español
- [ ] 7.1 Crear la estructura base de la interfaz
  - Definir la plantilla base con estilos livianos por CDN, la navegación entre la bandeja, el nuevo pedido y el pegado de texto, y los mensajes de la aplicación
  - Definir las rutas con espacio de nombres y redirigir la raíz a la bandeja
  - _Requirements: 12.4_

- [ ] 7.2 Implementar el formulario de pedido y el pegado de texto libre
  - Ofrecer un formulario con la dependencia y la descripción obligatorias, y la ubicación y el contacto opcionales; rechazar el envío incompleto indicando los campos faltantes y conservando lo ingresado
  - Ofrecer el pegado de texto libre con la dependencia opcional, y rechazar el texto vacío o compuesto solo por espacios, informando el motivo
  - Al enviar, registrar y priorizar el pedido y redirigir al detalle mostrando el identificador, la prioridad, el tipo y la justificación
  - Testear las vistas: errores de validación, redirección y mensajes en español
  - Requiere 6.3 y 7.1
  - _Requirements: 1.1, 1.3, 1.5, 2.1, 2.5_

- [ ] 7.3 Implementar la bandeja de triage
  - Mostrar para cada pedido el identificador, la fecha, la dependencia, la ubicación, el tipo, la prioridad, el puntaje y el estado, con el orden definido
  - Ofrecer los filtros por tipo, dependencia, prioridad y estado, conservando la selección
  - Destacar visualmente los pedidos P1 y los que están en "Requiere revisión", e indicar los valores corregidos
  - Mostrar un mensaje cuando no hay resultados y un contador de los pedidos sin clasificar
  - Testear el resaltado, la marca de corregido y el mensaje sin resultados
  - Requiere 6.5 y 7.1
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 7.4 Implementar el detalle del pedido con la confirmación y la corrección
  - Mostrar el texto original, la descripción normalizada, la dependencia, la ubicación, el canal, la fecha, los tipos y el estado
  - Mostrar los puntajes de todos los criterios con su evidencia, la confianza, el origen (IA o respaldo), los motivos de revisión y la justificación completa
  - Mostrar la recomendación original del sistema y el historial de correcciones cuando existen
  - Ofrecer las acciones de confirmar y de corregir (prioridad, tipo, motivo y responsable), recordando el responsable durante la sesión y mostrando los errores de validación
  - Testear la visualización del historial y los errores del motivo obligatorio
  - Requiere 6.4 y 7.1
  - _Requirements: 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.6_

- [ ] 8. Dataset de ejemplo y medición de aciertos
- [ ] 8.1 (P) Construir el dataset etiquetado de ejemplo
  - Redactar entre 15 y 20 pedidos realistas, con la prioridad y el tipo principal esperados según etiquetado manual
  - Cubrir todos los niveles P1–P4 (al menos 3 por nivel) y al menos 7 de los 9 tipos
  - Incluir casos de cada regla de escalamiento, un texto ambiguo de baja confianza y un texto libre sin dependencia
  - Validar la estructura del dataset con un test
  - _Requirements: 11.1_

- [ ] 8.2 Implementar la carga de los ejemplos en la bandeja
  - Registrar y priorizar cada pedido del dataset mediante el mismo caso de uso de registro, usando el caché de evaluaciones
  - Omitir los ejemplos ya cargados para que el comando sea idempotente
  - Testear la idempotencia y que los ejemplos aparezcan en la bandeja
  - Requiere 6.3, 4.3 y 8.1
  - _Requirements: 11.2, 11.4_

- [ ] 8.3 Implementar la evaluación de aciertos sobre el dataset
  - Ejecutar el triage de cada ejemplo sin persistirlo y comparar la prioridad final y el tipo principal con los valores esperados
  - Informar el porcentaje de coincidencia de prioridad y de tipo, el tiempo por pedido y su promedio, y el detalle de los casos no coincidentes con su origen
  - Permitir ejecutar sin caché o regenerarlo consultando a Gemini, y dejar generado el caché del dataset para la demo
  - Testear el cálculo de las métricas con evaluadores simulados
  - Requiere 5, 4.3 y 8.1
  - _Requirements: 3.7, 11.3, 11.4_

- [ ] 9. Integración final y verificación
- [ ] 9.1 Verificar de punta a punta los flujos principales
  - Probar el recorrido completo: registrar por formulario, verlo en la bandeja con su prioridad, abrir el detalle, corregirlo y ver la marca y el historial
  - Probar el recorrido con la IA no disponible: respaldo, "Requiere revisión" y justificación con el aviso de respaldo
  - Probar el recorrido con ambos evaluadores fallando: el pedido queda registrado sin clasificar y visible en la bandeja
  - Verificar que los datos de contacto nunca llegan a la request hacia la IA
  - _Requirements: 1.4, 1.5, 6.4, 6.5, 7.5, 8.3, 12.1_

- [ ] 9.2 Verificar el arranque con Docker Compose y la persistencia
  - Levantar todo con el comando único, cargar los ejemplos y comprobar que la bandeja responde
  - Reiniciar los contenedores y comprobar que los pedidos, los resultados y las correcciones se conservan
  - Comprobar con Gemini real que el triage de un pedido tarda menos de 10 segundos y que los secretos no aparecen en el repositorio
  - _Requirements: 3.7, 12.2, 12.3, 12.5_

- [ ]* 9.3 Ampliar los tests de presentación de la interfaz
  - Verificar que todas las pantallas y mensajes de error estén en español
  - Verificar el resaltado visual de P1 y de "Requiere revisión" en distintas combinaciones de filtros
  - Cubre criterios que ya satisfacen 7.3 y 7.4; se puede postergar después del MVP
  - _Requirements: 7.4, 12.4_
