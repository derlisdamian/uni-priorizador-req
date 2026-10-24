"""Modelos de persistencia: pedido, resultado del triage y correcciones (`pedidos.models`)."""

from decimal import Decimal

import pytest
from django.contrib import admin
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory

from pedidos.models import CorreccionManual, EstadoPedido, Pedido, ResultadoTriage
from triage.schemas import Canal

pytestmark = pytest.mark.django_db


def crear_pedido(**cambios) -> Pedido:
    valores = {
        "canal": Canal.FORMULARIO,
        "texto_original": "Hay cables expuestos en el pasillo",
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Pasillo del bloque B",
        "contacto": "ana@uni.edu.ar",
    }
    return Pedido.objects.create(**(valores | cambios))


def crear_resultado(pedido: Pedido, **cambios) -> ResultadoTriage:
    valores = {
        "pedido": pedido,
        "origen": "ia",
        "modelo": "gemini-3.8-flash",
        "tipo_principal": "Electricidad",
        "evaluacion": {"criterios": {"riesgo_personas": {"puntaje": 3, "evidencia": []}}},
        "puntaje_total": Decimal("71.00"),
        "prioridad_umbral": 1,
        "prioridad_final": 1,
        "justificacion_texto": "Prioridad P1.",
        "justificacion": {"texto": "Prioridad P1."},
        "intentos_ia": 1,
        "version_config": "abc123def456",
        "duracion_ms": 850,
    }
    return ResultadoTriage.objects.create(**(valores | cambios))


def crear_correccion(pedido: Pedido, **cambios) -> CorreccionManual:
    valores = {
        "pedido": pedido,
        "responsable": "Marta",
        "prioridad_anterior": 1,
        "prioridad_nueva": 2,
        "tipo_anterior": "Electricidad",
        "tipo_nuevo": "Electricidad",
        "motivo": "El tablero ya fue aislado",
    }
    return CorreccionManual.objects.create(**(valores | cambios))


class TestPedido:
    def test_valores_por_defecto_de_un_pedido_nuevo(self):
        pedido = crear_pedido()
        pedido.refresh_from_db()
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert pedido.motivos_revision == []
        assert pedido.prioridad_vigente is None
        assert pedido.tipo_vigente is None
        assert pedido.puntaje_total is None
        assert pedido.corregido is False
        assert pedido.recibido_en is not None
        assert pedido.codigo_ejemplo is None

    def test_identificador_legible(self):
        pedido = crear_pedido()
        assert pedido.identificador == f"PED-{pedido.pk:05d}"

    def test_estados_con_etiquetas_en_espanol(self):
        assert EstadoPedido.REQUIERE_REVISION.label == "Requiere revisión"
        assert EstadoPedido.PENDIENTE.label == "Pendiente"
        assert EstadoPedido.VALIDADO.label == "Validado"

    def test_el_texto_original_es_inmutable(self):
        pedido = crear_pedido()
        pedido.texto_original = "Otro texto"
        with pytest.raises(ValueError, match="inmutable"):
            pedido.save()
        pedido.refresh_from_db()
        assert pedido.texto_original == "Hay cables expuestos en el pasillo"

    def test_se_pueden_actualizar_los_demas_campos(self):
        pedido = crear_pedido()
        pedido.prioridad_vigente = 2
        pedido.estado = EstadoPedido.PENDIENTE
        pedido.save()
        pedido.refresh_from_db()
        assert pedido.prioridad_vigente == 2

    def test_el_texto_original_no_es_editable_en_formularios(self):
        assert Pedido._meta.get_field("texto_original").editable is False

    def test_prioridad_vigente_fuera_de_rango_es_rechazada_por_la_base(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            crear_pedido(prioridad_vigente=5)

    def test_codigo_de_ejemplo_unico(self):
        crear_pedido(codigo_ejemplo="EJ-01")
        crear_pedido(codigo_ejemplo=None)
        crear_pedido(codigo_ejemplo=None)
        with pytest.raises(IntegrityError), transaction.atomic():
            crear_pedido(codigo_ejemplo="EJ-01")

    def test_indices_de_la_bandeja(self):
        with connection.cursor() as cursor:
            restricciones = connection.introspection.get_constraints(cursor, "pedidos_pedido")
        indexados = {tuple(info["columns"]) for info in restricciones.values() if info["index"]}
        assert ("estado",) in indexados
        assert ("tipo_vigente",) in indexados
        assert ("dependencia",) in indexados
        assert any(nombre == "pedido_bandeja_orden_idx" for nombre in restricciones)


class TestResultadoTriage:
    def test_se_persiste_en_relacion_uno_a_uno(self):
        pedido = crear_pedido()
        resultado = crear_resultado(pedido)
        pedido.refresh_from_db()
        assert pedido.resultado == resultado
        assert resultado.evaluacion["criterios"]["riesgo_personas"]["puntaje"] == 3
        assert resultado.creado_en is not None

    def test_un_pedido_tiene_un_solo_resultado(self):
        pedido = crear_pedido()
        crear_resultado(pedido)
        with pytest.raises(IntegrityError), transaction.atomic():
            crear_resultado(pedido)

    def test_no_se_puede_modificar(self):
        resultado = crear_resultado(crear_pedido())
        resultado.prioridad_final = 4
        with pytest.raises(ValueError, match="solo por inserción"):
            resultado.save()
        resultado.refresh_from_db()
        assert resultado.prioridad_final == 1

    def test_no_se_puede_borrar_individualmente(self):
        resultado = crear_resultado(crear_pedido())
        with pytest.raises(ValueError, match="solo por inserción"):
            resultado.delete()

    def test_se_borra_en_cascada_con_el_pedido(self):
        pedido = crear_pedido()
        crear_resultado(pedido)
        pedido.delete()
        assert ResultadoTriage.objects.count() == 0


class TestCorreccionManual:
    def test_se_persiste_con_fecha_y_valores(self):
        correccion = crear_correccion(crear_pedido())
        correccion.refresh_from_db()
        assert correccion.creado_en is not None
        assert (correccion.prioridad_anterior, correccion.prioridad_nueva) == (1, 2)

    def test_motivo_vacio_rechazado_por_la_base(self):
        pedido = crear_pedido()
        for motivo in ["", "   ", "\n\t"]:
            with pytest.raises(IntegrityError), transaction.atomic():
                crear_correccion(pedido, motivo=motivo)

    def test_responsable_vacio_rechazado_por_la_base(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            crear_correccion(crear_pedido(), responsable="  ")

    def test_prioridad_nueva_fuera_de_rango_rechazada_por_la_base(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            crear_correccion(crear_pedido(), prioridad_nueva=0)

    def test_prioridad_anterior_nula_para_pedidos_sin_clasificacion(self):
        correccion = crear_correccion(crear_pedido(), prioridad_anterior=None, tipo_anterior=None)
        assert correccion.pk is not None

    def test_no_se_puede_modificar(self):
        correccion = crear_correccion(crear_pedido())
        correccion.motivo = "Otro motivo"
        with pytest.raises(ValueError, match="solo por inserción"):
            correccion.save()

    def test_historial_de_la_mas_reciente_a_la_mas_antigua(self):
        pedido = crear_pedido()
        primera = crear_correccion(pedido)
        segunda = crear_correccion(pedido, prioridad_anterior=2, prioridad_nueva=3)
        assert list(pedido.correcciones.all()) == [segunda, primera]


class TestAdmin:
    @pytest.fixture
    def request_admin(self):
        request = RequestFactory().get("/admin/")
        request.user = type(
            "Superusuario",
            (),
            {
                "is_active": True,
                "is_staff": True,
                "is_superuser": True,
                "has_perm": lambda *a, **k: True,
            },
        )()
        return request

    def test_los_tres_modelos_estan_registrados(self):
        for modelo in (Pedido, ResultadoTriage, CorreccionManual):
            assert admin.site.is_registered(modelo)

    @pytest.mark.parametrize("modelo", [ResultadoTriage, CorreccionManual])
    def test_resultados_y_correcciones_son_de_solo_lectura(self, modelo, request_admin):
        modelo_admin = admin.site._registry[modelo]
        assert modelo_admin.has_add_permission(request_admin) is False
        assert modelo_admin.has_change_permission(request_admin) is False
        assert modelo_admin.has_delete_permission(request_admin) is False
        assert modelo_admin.has_view_permission(request_admin) is True

    def test_el_texto_original_se_muestra_pero_no_se_edita(self, request_admin):
        modelo_admin = admin.site._registry[Pedido]
        assert "texto_original" in modelo_admin.get_readonly_fields(request_admin)
