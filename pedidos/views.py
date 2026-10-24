"""Vistas de la interfaz web: validan la entrada, delegan en `ServicioPedidos` y renderizan."""

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from pedidos import configuracion
from pedidos.consultas import FiltrosBandeja, consultar_bandeja, opciones_filtros
from pedidos.forms import (
    FormularioCorreccion,
    FormularioFiltros,
    FormularioPedido,
    FormularioResponsable,
    FormularioTextoLibre,
)
from pedidos.models import Pedido
from pedidos.services import DatosPedido, ErrorOperacion, ServicioPedidos
from triage.schemas import Canal

CLAVE_RESPONSABLE = "responsable"  # se recuerda en la sesión para no tipearlo de nuevo

ETIQUETAS_MOTIVO = {
    "confianza_baja": "Confianza baja",
    "texto_insuficiente": "Texto insuficiente para evaluar",
    "conflicto_tipos": "Conflicto entre tipos candidatos",
    "dependencia_no_informada": "Dependencia no informada",
    "ubicacion_no_informada": "Ubicación no informada",
    "clasificacion_respaldo": "Clasificación de respaldo (sin IA)",
    "sin_clasificacion": "Sin clasificación",
}


def obtener_servicio() -> ServicioPedidos:
    return ServicioPedidos.desde_settings()


def _registrar_y_mostrar(request: HttpRequest, datos: DatosPedido) -> HttpResponse:
    pedido = obtener_servicio().registrar(datos)
    if pedido.prioridad_vigente is not None:
        messages.success(
            request,
            f"Pedido {pedido.identificador} registrado: prioridad "
            f"{pedido.get_prioridad_vigente_display()}, tipo {pedido.tipo_vigente}.",
        )
    elif Pedido.objects.filter(pk=pedido.pk, resultado__isnull=False).exists():
        messages.warning(
            request,
            f"Pedido {pedido.identificador} registrado sin clasificación; requiere revisión.",
        )
    else:
        messages.error(
            request,
            f"El pedido se registró pero no pudo priorizarse ({pedido.identificador}).",
        )
    return redirect("pedidos:detalle", pedido.pk)


def nuevo(request: HttpRequest) -> HttpResponse:
    formulario = FormularioPedido(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        return _registrar_y_mostrar(
            request,
            DatosPedido(
                canal=Canal.FORMULARIO,
                texto=datos["descripcion"],
                dependencia=datos["dependencia"],
                ubicacion=datos["ubicacion"],
                contacto=datos["contacto"],
            ),
        )
    return render(request, "pedidos/nuevo.html", {"formulario": formulario})


def texto_libre(request: HttpRequest) -> HttpResponse:
    formulario = FormularioTextoLibre(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        return _registrar_y_mostrar(
            request,
            DatosPedido(
                canal=Canal.TEXTO_LIBRE,
                texto=datos["texto"],
                dependencia=datos["dependencia"],
                ubicacion=None,
                contacto=None,
            ),
        )
    return render(request, "pedidos/texto.html", {"formulario": formulario})


def bandeja(request: HttpRequest) -> HttpResponse:
    formulario = FormularioFiltros(
        request.GET or None, opciones=opciones_filtros(configuracion.obtener())
    )
    filtros = FiltrosBandeja()
    if formulario.is_bound:
        if not formulario.is_valid():
            ignorados = ", ".join(formulario.fields[campo].label for campo in formulario.errors)
            messages.warning(request, f"Se ignoraron filtros inválidos: {ignorados}.")
        filtros = formulario.filtros()
    contexto = {
        "formulario": formulario,
        "pedidos": consultar_bandeja(filtros),
        "sin_clasificar": Pedido.objects.filter(prioridad_vigente__isnull=True).count(),
    }
    return render(request, "pedidos/bandeja.html", contexto)


def _criterios(pedido: Pedido) -> list[dict]:
    """Los criterios configurados con el puntaje y la evidencia del resultado."""
    resultado = getattr(pedido, "resultado", None)
    evaluados = (resultado.evaluacion or {}).get("criterios", {}) if resultado else {}
    return [
        {
            "nombre": definicion.nombre,
            "informativo": definicion.informativo,
            "puntaje": evaluados.get(definicion.clave, {}).get("puntaje"),
            "evidencia": evaluados.get(definicion.clave, {}).get("evidencia", []),
        }
        for definicion in configuracion.obtener().criterios
    ]


def _render_detalle(
    request: HttpRequest,
    pedido: Pedido,
    *,
    correccion: FormularioCorreccion | None = None,
    confirmacion: FormularioResponsable | None = None,
    status: int = 200,
) -> HttpResponse:
    responsable = request.session.get(CLAVE_RESPONSABLE, "")
    resultado = getattr(pedido, "resultado", None)
    contexto = {
        "pedido": pedido,
        "resultado": resultado,
        "criterios": _criterios(pedido),
        "motivos": [ETIQUETAS_MOTIVO.get(m, m) for m in pedido.motivos_revision],
        "correcciones": pedido.correcciones.all(),
        "confirmacion": confirmacion or FormularioResponsable(initial={"responsable": responsable}),
        "correccion": correccion
        or FormularioCorreccion(
            tipos=configuracion.obtener().nombres_tipos(),
            initial={
                "prioridad": pedido.prioridad_vigente,
                "tipo": pedido.tipo_vigente,
                "responsable": responsable,
            },
        ),
    }
    return render(request, "pedidos/detalle.html", contexto, status=status)


def detalle(request: HttpRequest, pedido_id: int) -> HttpResponse:
    return _render_detalle(request, get_object_or_404(Pedido, pk=pedido_id))


@require_POST
def confirmar(request: HttpRequest, pedido_id: int) -> HttpResponse:
    pedido = get_object_or_404(Pedido, pk=pedido_id)
    formulario = FormularioResponsable(request.POST)
    if not formulario.is_valid():
        return _render_detalle(request, pedido, confirmacion=formulario)
    responsable = formulario.cleaned_data["responsable"]
    request.session[CLAVE_RESPONSABLE] = responsable
    try:
        obtener_servicio().confirmar(pedido.pk, responsable)
    except ErrorOperacion as error:
        formulario.add_error(None, error.mensaje)
        return _render_detalle(request, pedido, confirmacion=formulario, status=400)
    messages.success(request, f"Pedido {pedido.identificador} validado.")
    return redirect("pedidos:detalle", pedido.pk)


@require_POST
def corregir(request: HttpRequest, pedido_id: int) -> HttpResponse:
    pedido = get_object_or_404(Pedido, pk=pedido_id)
    formulario = FormularioCorreccion(request.POST, tipos=configuracion.obtener().nombres_tipos())
    if not formulario.is_valid():
        return _render_detalle(request, pedido, correccion=formulario)
    datos = formulario.cleaned_data
    request.session[CLAVE_RESPONSABLE] = datos["responsable"]
    try:
        obtener_servicio().corregir(
            pedido.pk,
            prioridad=datos["prioridad"],
            tipo=datos["tipo"],
            motivo=datos["motivo"],
            responsable=datos["responsable"],
        )
    except ErrorOperacion as error:
        formulario.add_error(None, error.mensaje)
        return _render_detalle(request, pedido, correccion=formulario)
    messages.success(request, f"Corrección del pedido {pedido.identificador} registrada.")
    return redirect("pedidos:detalle", pedido.pk)
