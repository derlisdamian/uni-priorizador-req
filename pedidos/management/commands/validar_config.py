from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from triage.config import ConfiguracionInvalida, cargar_configuracion


class Command(BaseCommand):
    help = "Valida la configuración de triage (config/*.yaml) e informa su versión o sus errores."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--directorio",
            type=Path,
            default=None,
            help="Directorio con criterios.yaml y tipos.yaml (por defecto, TRIAGE_CONFIG_DIR).",
        )

    def handle(self, *args, directorio: Path | None, **opciones):
        # Se lee del disco: refleja los cambios aunque el proceso no se haya reiniciado.
        try:
            config = cargar_configuracion(directorio or settings.TRIAGE_CONFIG_DIR)
        except ConfiguracionInvalida as error:
            raise CommandError(str(error), returncode=1) from error
        self.stdout.write(self.style.SUCCESS(f"Configuración válida (versión {config.version})"))
