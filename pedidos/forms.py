"""Formularios de la interfaz: validan la entrada del usuario con mensajes en español."""

from django import forms

from pedidos.consultas import FiltrosBandeja, OpcionesFiltros
from pedidos.models import EstadoPedido
from triage.schemas import Prioridad

OPCION_INVALIDA = "Elegí una opción válida."
OPCIONES_PRIORIDAD = [(p.value, p.name) for p in Prioridad]


def _obligatorio(mensaje: str) -> dict[str, str]:
    return {"required": mensaje}


class FormularioPedido(forms.Form):
    dependencia = forms.CharField(
        label="Dependencia solicitante",
        max_length=200,
        error_messages=_obligatorio("La dependencia es obligatoria."),
    )
    ubicacion = forms.CharField(
        label="Ubicación",
        max_length=300,
        required=False,
        help_text="Edificio, piso o espacio.",
    )
    descripcion = forms.CharField(
        label="Descripción del problema",
        widget=forms.Textarea(attrs={"rows": 5}),
        error_messages=_obligatorio("La descripción del problema es obligatoria."),
    )
    contacto = forms.CharField(label="Datos de contacto (opcional)", max_length=300, required=False)


class FormularioTextoLibre(forms.Form):
    # Sin strip: el pedido se registra con el texto original íntegro (requisito 2.2).
    texto = forms.CharField(
        label="Texto del correo o nota",
        strip=False,
        widget=forms.Textarea(attrs={"rows": 10}),
        error_messages=_obligatorio("El texto no puede estar vacío."),
    )
    dependencia = forms.CharField(label="Dependencia (opcional)", max_length=200, required=False)

    def clean_texto(self) -> str:
        texto = self.cleaned_data["texto"]
        if not texto.strip():
            raise forms.ValidationError("El texto no puede estar vacío.")
        return texto


class FormularioResponsable(forms.Form):
    responsable = forms.CharField(
        label="Responsable",
        max_length=100,
        error_messages=_obligatorio("El responsable es obligatorio."),
    )


class FormularioCorreccion(FormularioResponsable):
    prioridad = forms.TypedChoiceField(
        label="Prioridad",
        choices=OPCIONES_PRIORIDAD,
        coerce=int,
        error_messages={"invalid_choice": OPCION_INVALIDA},
    )
    tipo = forms.ChoiceField(label="Tipo", error_messages={"invalid_choice": OPCION_INVALIDA})
    motivo = forms.CharField(
        label="Motivo",
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages=_obligatorio("El motivo es obligatorio."),
    )

    field_order = ["prioridad", "tipo", "motivo", "responsable"]

    def __init__(self, *args, tipos: list[str], **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].choices = [(tipo, tipo) for tipo in tipos]


class FormularioFiltros(forms.Form):
    """Filtros de la bandeja; un valor inválido se ignora y se informa."""

    tipo = forms.ChoiceField(label="Tipo", required=False)
    dependencia = forms.ChoiceField(label="Dependencia", required=False)
    prioridad = forms.TypedChoiceField(
        label="Prioridad", required=False, coerce=int, empty_value=None
    )
    estado = forms.ChoiceField(label="Estado", required=False)

    def __init__(self, *args, opciones: OpcionesFiltros, **kwargs):
        super().__init__(*args, **kwargs)
        todos = [("", "Todos")]
        self.fields["tipo"].choices = todos + [(t, t) for t in opciones.tipos]
        self.fields["dependencia"].choices = todos + [(d, d) for d in opciones.dependencias]
        self.fields["prioridad"].choices = todos + [(p.value, p.name) for p in opciones.prioridades]
        self.fields["estado"].choices = todos + opciones.estados

    def filtros(self) -> FiltrosBandeja:
        """Los filtros válidos; requiere haber llamado a `is_valid()`."""
        datos = self.cleaned_data
        prioridad = datos.get("prioridad")
        estado = datos.get("estado")
        return FiltrosBandeja(
            tipo=datos.get("tipo") or None,
            dependencia=datos.get("dependencia") or None,
            prioridad=Prioridad(prioridad) if prioridad else None,
            estado=EstadoPedido(estado) if estado else None,
        )
