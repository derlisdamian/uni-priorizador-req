"""Modelos ORM de pedidos, resultados de triage y correcciones manuales."""

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from triage.schemas import Canal, OrigenResultado, Prioridad

NO_INFORMADO = "No informado"

OPCIONES_CANAL = [(Canal.FORMULARIO.value, "Formulario"), (Canal.TEXTO_LIBRE.value, "Texto libre")]
OPCIONES_ORIGEN = [
    (OrigenResultado.IA.value, "IA"),
    (OrigenResultado.RESPALDO.value, "Respaldo por palabras clave"),
    (OrigenResultado.SIN_CLASIFICACION.value, "Sin clasificación"),
]
OPCIONES_PRIORIDAD = [(p.value, p.name) for p in Prioridad]


def _en_rango(campo: str) -> Q:
    return Q(**{f"{campo}__gte": Prioridad.P1, f"{campo}__lte": Prioridad.P4})


def _no_vacio(campo: str) -> Q:
    return Q(**{f"{campo}__regex": r"\S"})


class EstadoPedido(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    REQUIERE_REVISION = "requiere_revision", "Requiere revisión"
    VALIDADO = "validado", "Validado"


class SoloInsercion(models.Model):
    """Registro histórico: se crea una vez y nunca se modifica ni se borra individualmente."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError(f"{self._meta.verbose_name} se guarda solo por inserción")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(f"{self._meta.verbose_name} se guarda solo por inserción")


class Pedido(models.Model):
    canal = models.CharField(max_length=20, choices=OPCIONES_CANAL)
    texto_original = models.TextField(editable=False)  # inmutable (requisito 3.6)
    # Resueltas: la informada, luego la extraída del texto, luego "No informado"
    dependencia = models.CharField(max_length=200, db_index=True)
    ubicacion = models.CharField(max_length=300)
    contacto = models.CharField(max_length=300, null=True, blank=True)  # nunca va a la IA
    recibido_en = models.DateTimeField(default=timezone.now)
    estado = models.CharField(
        max_length=20,
        choices=EstadoPedido.choices,
        default=EstadoPedido.REQUIERE_REVISION,
        db_index=True,
    )
    motivos_revision = models.JSONField(default=list, blank=True)  # list[MotivoRevision]
    # Valores vigentes, desnormalizados para ordenar y filtrar la bandeja
    prioridad_vigente = models.PositiveSmallIntegerField(
        choices=OPCIONES_PRIORIDAD, null=True, blank=True
    )
    tipo_vigente = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    puntaje_total = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    corregido = models.BooleanField(default=False)
    validado_en = models.DateTimeField(null=True, blank=True)
    validado_por = models.CharField(max_length=100, null=True, blank=True)
    codigo_ejemplo = models.CharField(max_length=20, null=True, blank=True, unique=True)

    class Meta:
        verbose_name = "pedido"
        indexes = [
            models.Index(
                F("prioridad_vigente").asc(nulls_last=True),
                F("puntaje_total").desc(nulls_last=True),
                "recibido_en",
                name="pedido_bandeja_orden_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=_en_rango("prioridad_vigente"), name="pedido_prioridad_vigente_p1_p4"
            ),
        ]

    def __str__(self) -> str:
        return self.identificador

    def save(self, *args, **kwargs):
        guardado = getattr(self, "_texto_original_guardado", None)
        if not self._state.adding and guardado is not None and guardado != self.texto_original:
            raise ValueError("El texto original del pedido es inmutable")
        super().save(*args, **kwargs)
        self._texto_original_guardado = self.texto_original

    @classmethod
    def from_db(cls, db, field_names, values):
        instancia = super().from_db(db, field_names, values)
        instancia._texto_original_guardado = instancia.__dict__.get("texto_original")
        return instancia

    @property
    def identificador(self) -> str:
        return f"PED-{self.pk:05d}"


class ResultadoTriage(SoloInsercion):
    """Recomendación original del sistema: nunca se sobrescribe (requisito 9.4)."""

    pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE, related_name="resultado")
    origen = models.CharField(max_length=20, choices=OPCIONES_ORIGEN)
    modelo = models.CharField(max_length=60, null=True, blank=True)
    descripcion_normalizada = models.TextField(null=True, blank=True)
    tipo_principal = models.CharField(max_length=50, null=True, blank=True)
    tipos_secundarios = models.JSONField(default=list, blank=True)
    evaluacion = models.JSONField(null=True, blank=True)  # EvaluacionCriterios completa
    confianza = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    puntaje_total = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    prioridad_umbral = models.PositiveSmallIntegerField(
        choices=OPCIONES_PRIORIDAD, null=True, blank=True
    )
    prioridad_final = models.PositiveSmallIntegerField(
        choices=OPCIONES_PRIORIDAD, null=True, blank=True
    )
    reglas_aplicadas = models.JSONField(default=list, blank=True)
    justificacion_texto = models.TextField()
    justificacion = models.JSONField()
    motivos_revision = models.JSONField(default=list, blank=True)  # motivos originales
    intentos_ia = models.PositiveSmallIntegerField(default=0)
    errores = models.JSONField(default=list, blank=True)
    version_config = models.CharField(max_length=16)  # requisito 10.4
    duracion_ms = models.PositiveIntegerField()
    creado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "resultado del triage"
        verbose_name_plural = "resultados del triage"

    def __str__(self) -> str:
        return f"Resultado de {self.pedido}"


class CorreccionManual(SoloInsercion):
    """Historial de correcciones: la más reciente es la vigente (requisito 9.5)."""

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="correcciones")
    creado_en = models.DateTimeField(default=timezone.now)
    responsable = models.CharField(max_length=100)
    prioridad_anterior = models.PositiveSmallIntegerField(
        choices=OPCIONES_PRIORIDAD, null=True, blank=True
    )
    prioridad_nueva = models.PositiveSmallIntegerField(choices=OPCIONES_PRIORIDAD)
    tipo_anterior = models.CharField(max_length=50, null=True, blank=True)
    tipo_nuevo = models.CharField(max_length=50)
    motivo = models.TextField()

    class Meta:
        verbose_name = "corrección manual"
        verbose_name_plural = "correcciones manuales"
        ordering = ["-creado_en", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=_en_rango("prioridad_nueva"), name="correccion_prioridad_nueva_p1_p4"
            ),
            models.CheckConstraint(
                condition=_en_rango("prioridad_anterior") | Q(prioridad_anterior__isnull=True),
                name="correccion_prioridad_anterior_p1_p4",
            ),
            models.CheckConstraint(
                condition=_no_vacio("motivo"), name="correccion_motivo_obligatorio"
            ),
            models.CheckConstraint(
                condition=_no_vacio("responsable"), name="correccion_responsable_obligatorio"
            ),
        ]

    def __str__(self) -> str:
        return f"Corrección de {self.pedido} ({self.creado_en:%d/%m/%Y %H:%M})"
