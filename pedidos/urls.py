from django.urls import path

from pedidos import views

app_name = "pedidos"

urlpatterns = [
    path("", views.bandeja, name="bandeja"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("texto/", views.texto_libre, name="texto"),
    path("<int:pedido_id>/", views.detalle, name="detalle"),
    path("<int:pedido_id>/confirmar/", views.confirmar, name="confirmar"),
    path("<int:pedido_id>/corregir/", views.corregir, name="corregir"),
]
