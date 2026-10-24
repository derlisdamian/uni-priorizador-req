import sys

from django.apps import AppConfig
from django.conf import settings


class PedidosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pedidos"
    verbose_name = "Pedidos de mantenimiento"

    def ready(self):
        from pedidos import configuracion

        # `validar_config` existe para diagnosticar una configuración inválida, así que en ese
        # comando la carga no puede impedir el arranque: el comando informa los errores.
        diagnosticando = sys.argv[1:2] == ["validar_config"]
        configuracion.inicializar(settings.TRIAGE_CONFIG_DIR, estricto=not diagnosticando)
