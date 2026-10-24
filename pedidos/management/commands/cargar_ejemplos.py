from functools import partial
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from pedidos import configuracion
from pedidos.models import Pedido
from pedidos.services import DatosPedido, ServicioPedidos, construir_evaluadores
from triage.dataset import DatasetInvalido, cargar_dataset


def dataset_por_defecto() -> Path:
    return Path(settings.BASE_DIR) / "data" / "pedidos_ejemplo.json"


class Command(BaseCommand):
    help = "Registra y prioriza los pedidos del dataset de ejemplo; omite los ya cargados."

    def add_arguments(self, parser):
        parser.add_argument(
            "--archivo",
            type=Path,
            default=None,
            help="Dataset JSON (por defecto, data/pedidos_ejemplo.json).",
        )

    def handle(self, *args, archivo: Path | None, **opciones):
        config = configuracion.obtener()
        try:
            ejemplos = cargar_dataset(archivo or dataset_por_defecto(), config)
        except DatasetInvalido as error:
            raise CommandError(str(error)) from error

        existentes = set(
            Pedido.objects.filter(
                codigo_ejemplo__in=[e.codigo_ejemplo for e in ejemplos]
            ).values_list("codigo_ejemplo", flat=True)
        )
        pendientes = [e for e in ejemplos if e.codigo_ejemplo not in existentes]
        if pendientes:
            # Con caché: la demo reutiliza las evaluaciones guardadas sin consultar a Gemini.
            servicio = ServicioPedidos.desde_settings(
                partial(construir_evaluadores, usar_cache=True)
            )
            for e in pendientes:
                pedido = servicio.registrar(
                    DatosPedido(
                        canal=e.canal,
                        texto=e.texto,
                        dependencia=e.dependencia,
                        ubicacion=e.ubicacion,
                        contacto=None,
                        codigo_ejemplo=e.codigo_ejemplo,
                    )
                )
                prioridad = pedido.get_prioridad_vigente_display() or "sin clasificar"
                self.stdout.write(f"{e.codigo_ejemplo} → {pedido.identificador} ({prioridad})")

        resumen = f"Ejemplos: {len(pendientes)} cargados, {len(existentes)} omitidos"
        self.stdout.write(self.style.SUCCESS(f"{resumen} (ya estaban cargados)"))
