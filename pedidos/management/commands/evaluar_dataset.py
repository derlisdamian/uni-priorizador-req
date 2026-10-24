from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from pedidos import configuracion
from pedidos.management.commands.cargar_ejemplos import dataset_por_defecto
from pedidos.services import construir_evaluadores
from triage.dataset import DatasetInvalido, cargar_dataset, formatear_reporte, medir_aciertos


class Command(BaseCommand):
    help = (
        "Ejecuta el triage del dataset etiquetado sin persistirlo e informa los aciertos de "
        "prioridad y tipo, los tiempos y los casos no coincidentes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "archivo",
            type=Path,
            nargs="?",
            default=None,
            help="Dataset JSON (por defecto, data/pedidos_ejemplo.json).",
        )
        cache = parser.add_mutually_exclusive_group()
        cache.add_argument(
            "--sin-cache", action="store_true", help="Consulta a la IA sin usar el caché."
        )
        cache.add_argument(
            "--refrescar-cache",
            action="store_true",
            help="Consulta a Gemini y regenera el caché de evaluaciones del dataset.",
        )

    def handle(self, *args, archivo: Path | None, sin_cache: bool, refrescar_cache: bool, **_):
        config = configuracion.obtener()
        try:
            ejemplos = cargar_dataset(archivo or dataset_por_defecto(), config)
        except DatasetInvalido as error:
            raise CommandError(str(error)) from error
        if refrescar_cache and not settings.GEMINI_API_KEY:
            raise CommandError("Para regenerar el caché hace falta configurar GEMINI_API_KEY.")

        principal, respaldo = construir_evaluadores(
            config, usar_cache=not sin_cache, refrescar_cache=refrescar_cache
        )
        reporte = medir_aciertos(ejemplos, principal, respaldo, config)
        self.stdout.write(formatear_reporte(reporte))
        if refrescar_cache:
            self.stdout.write(
                self.style.SUCCESS(f"Caché regenerado en {settings.TRIAGE_CACHE_ARCHIVO}")
            )
