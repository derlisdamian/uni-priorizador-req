# Priorizador de pedidos de obras y mantenimiento

Triage de pedidos de mantenimiento de la universidad: interpreta cada pedido con Gemini y recomienda una prioridad P1–P4 con una justificación explicable.

## Puesta en marcha

Requisito: Docker con Compose v2.

1. Crear el archivo de entorno y completar `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` y `GEMINI_API_KEY`:

   ```bash
   cp .env.example .env
   ```

2. Levantar la aplicación y la base de datos con un solo comando:

   ```bash
   docker compose up --build
   ```

   Las migraciones se aplican al arrancar. La aplicación queda en <http://localhost:8000>.

Sin `GEMINI_API_KEY` la aplicación funciona igual, con la clasificación de respaldo por palabras clave.

## Comandos opcionales de demo

```bash
# Cargar los pedidos de ejemplo en la bandeja
docker compose exec web python manage.py cargar_ejemplos

# Medir los aciertos de prioridad y tipo sobre el dataset etiquetado
docker compose exec web python manage.py evaluar_dataset data/pedidos_ejemplo.json
#   --sin-cache: consulta a la IA sin caché · --refrescar-cache: regenera el caché con Gemini
#   (requiere GEMINI_API_KEY; luego versionar data/cache/evaluaciones.json)

# Crear un usuario para el admin
docker compose exec web python manage.py createsuperuser

# Ejecutar los tests
docker compose exec web pytest
```

Para detener todo: `docker compose down` (agregar `-v` para borrar también la base de datos).
