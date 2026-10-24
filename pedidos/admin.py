"""Registro de los modelos en el admin. Resultados y correcciones son de solo lectura."""

from django.contrib import admin

from pedidos.models import CorreccionManual, Pedido, ResultadoTriage


class SoloLecturaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ResultadoInline(admin.StackedInline):
    model = ResultadoTriage
    can_delete = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class CorreccionInline(admin.TabularInline):
    model = CorreccionManual
    can_delete = False
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = [
        "identificador",
        "recibido_en",
        "dependencia",
        "tipo_vigente",
        "prioridad_vigente",
        "puntaje_total",
        "estado",
        "corregido",
    ]
    list_filter = ["estado", "prioridad_vigente", "tipo_vigente", "canal", "corregido"]
    search_fields = ["dependencia", "ubicacion", "codigo_ejemplo"]
    readonly_fields = ["texto_original", "recibido_en"]
    inlines = [ResultadoInline, CorreccionInline]


@admin.register(ResultadoTriage)
class ResultadoTriageAdmin(SoloLecturaAdmin):
    list_display = ["pedido", "origen", "prioridad_final", "puntaje_total", "version_config"]
    list_filter = ["origen", "prioridad_final"]


@admin.register(CorreccionManual)
class CorreccionManualAdmin(SoloLecturaAdmin):
    list_display = ["pedido", "creado_en", "responsable", "prioridad_nueva", "tipo_nuevo"]
