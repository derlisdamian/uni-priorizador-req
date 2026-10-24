"""Rutas raíz del proyecto: la raíz redirige a la bandeja de triage."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="pedidos:bandeja", permanent=False)),
    path("pedidos/", include("pedidos.urls")),
    path("admin/", admin.site.urls),
]
