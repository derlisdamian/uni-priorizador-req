"""Casos de uso de la aplicación: registrar, confirmar y corregir pedidos.

Las vistas y los comandos solo validan la entrada y delegan aquí; la priorización vive en
`triage/` y este módulo traduce entre el dominio y los modelos ORM.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from pedidos import configuracion
from pedidos.models import (
    NO_INFORMADO,
    CorreccionManual,
    EstadoPedido,
    Pedido,
    ResultadoTriage,
)
from triage.config import ConfiguracionTriage
from triage.evaluadores import EvaluadorPedidos
from triage.evaluadores.cache import envolver_con_cache
from triage.evaluadores.gemini import EvaluadorGemini
from triage.evaluadores.palabras_clave import EvaluadorPalabrasClave
from triage.pipeline import construir_entrada, triar_pedido
from triage.schemas import Canal, MotivoRevision, Prioridad
from triage.schemas import ResultadoTriage as ResultadoDominio

logger = logging.getLogger("triage")

LIMITE_DURACION_MS = 10_000  # requisito 3.7

ConstructorEvaluadores = Callable[[ConfiguracionTriage], tuple[EvaluadorPedidos, EvaluadorPedidos]]


@dataclass(frozen=True)
class DatosPedido:
    canal: Canal
    texto: str
    dependencia: str | None
    ubicacion: str | None
    contacto: str | None  # se persiste, nunca se envía a la IA
    codigo_ejemplo: str | None = None  # solo para los pedidos del dataset de ejemplo


class ErrorOperacion(Exception):
    """Operación rechazada; el mensaje se dirige al usuario, en español."""

    def __init__(self, mensaje: str):
        self.mensaje = mensaje
        super().__init__(mensaje)


def construir_evaluadores(
    config: ConfiguracionTriage,
    *,
    usar_cache: bool | None = None,
    refrescar_cache: bool = False,
) -> tuple[EvaluadorPedidos, EvaluadorPedidos]:
    """Gemini (con caché opcional) como evaluador principal y palabras clave como respaldo.

    Sin `usar_cache` decide `TRIAGE_USAR_CACHE`; los comandos del dataset lo fuerzan.
    """
    gemini = EvaluadorGemini(
        config,
        api_key=settings.GEMINI_API_KEY,
        modelo=settings.GEMINI_MODEL,
        timeout_s=settings.GEMINI_TIMEOUT_S,
    )
    principal = envolver_con_cache(
        gemini,
        usar_cache=settings.TRIAGE_USAR_CACHE if usar_cache is None else usar_cache,
        archivo=settings.TRIAGE_CACHE_ARCHIVO,
        refrescar=refrescar_cache,
    )
    return principal, EvaluadorPalabrasClave(config)


def _limpio(valor: str | None) -> str | None:
    return valor.strip() or None if valor else None


def _resuelto(*candidatos: str | None) -> str:
    return next((v for v in map(_limpio, candidatos) if v), NO_INFORMADO)


def _dos_decimales(valor: float) -> Decimal:
    # Se trunca para que una confianza de 0,595 no se muestre como 0,60 siendo baja.
    return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def _obligatorio(valor: str | None, mensaje: str) -> str:
    limpio = _limpio(valor)
    if limpio is None:
        raise ErrorOperacion(mensaje)
    return limpio


def _prioridad(valor: object) -> Prioridad:
    if isinstance(valor, int) and not isinstance(valor, bool) and valor in Prioridad:
        return Prioridad(valor)
    raise ErrorOperacion("La prioridad debe ser P1, P2, P3 o P4")


def _bloquear(pedido_id: int) -> Pedido:
    """Obtiene el pedido bloqueándolo hasta el final de la transacción."""
    try:
        return Pedido.objects.select_for_update().get(pk=pedido_id)
    except Pedido.DoesNotExist:
        raise ErrorOperacion(f"El pedido {pedido_id} no existe") from None


def _validar(pedido: Pedido, responsable: str) -> None:
    pedido.estado = EstadoPedido.VALIDADO
    pedido.validado_en = timezone.now()
    pedido.validado_por = responsable


class ServicioPedidos:
    def __init__(
        self,
        config: ConfiguracionTriage,
        principal: EvaluadorPedidos,
        respaldo: EvaluadorPedidos,
    ) -> None:
        self.config = config
        self.principal = principal
        self.respaldo = respaldo

    @classmethod
    def desde_settings(
        cls, construir: ConstructorEvaluadores = construir_evaluadores
    ) -> "ServicioPedidos":
        config = configuracion.obtener()
        return cls(config, *construir(config))

    def registrar(self, datos: DatosPedido) -> Pedido:
        """Registra el pedido y lo prioriza. El pedido queda guardado aunque todo falle."""
        # Se guarda antes de evaluarlo, en revisión y sin clasificar (requisito 6.5).
        pedido = Pedido.objects.create(
            canal=datos.canal,
            texto_original=datos.texto,
            dependencia=_resuelto(datos.dependencia),
            ubicacion=_resuelto(datos.ubicacion),
            contacto=_limpio(datos.contacto),
            estado=EstadoPedido.REQUIERE_REVISION,
            motivos_revision=[MotivoRevision.SIN_CLASIFICACION],
            codigo_ejemplo=datos.codigo_ejemplo,
        )
        try:
            entrada = construir_entrada(
                datos.texto,
                canal=datos.canal,
                dependencia=datos.dependencia,
                ubicacion=datos.ubicacion,
            )
            resultado = triar_pedido(entrada, self.principal, self.respaldo, self.config)
            with transaction.atomic():
                self._aplicar_resultado(pedido, datos, resultado)
        except Exception:
            logger.exception("El pedido %s se registró pero no pudo priorizarse", pedido.pk)
            pedido.refresh_from_db()
            return pedido
        self._registrar_en_log(pedido, resultado)
        return pedido

    def _aplicar_resultado(
        self, pedido: Pedido, datos: DatosPedido, resultado: ResultadoDominio
    ) -> None:
        evaluacion, calculo = resultado.evaluacion, resultado.calculo
        ResultadoTriage.objects.create(
            pedido=pedido,
            origen=resultado.origen,
            modelo=resultado.modelo,
            descripcion_normalizada=evaluacion and evaluacion.descripcion_normalizada,
            tipo_principal=evaluacion and evaluacion.tipo_principal,
            tipos_secundarios=evaluacion.tipos_secundarios if evaluacion else [],
            evaluacion=evaluacion and evaluacion.model_dump(mode="json"),
            confianza=evaluacion and _dos_decimales(evaluacion.confianza),
            puntaje_total=calculo and calculo.puntaje_total,
            prioridad_umbral=calculo and calculo.prioridad_umbral,
            prioridad_final=calculo and calculo.prioridad_final,
            reglas_aplicadas=[r.model_dump(mode="json") for r in calculo.reglas_aplicadas]
            if calculo
            else [],
            justificacion_texto=resultado.justificacion.texto,
            justificacion=resultado.justificacion.model_dump(mode="json"),
            motivos_revision=[str(m) for m in resultado.motivos_revision],
            intentos_ia=resultado.intentos_ia,
            errores=resultado.errores,
            version_config=resultado.version_config,
            duracion_ms=resultado.duracion_ms,
        )
        pedido.dependencia = _resuelto(datos.dependencia, evaluacion and evaluacion.dependencia)
        pedido.ubicacion = _resuelto(datos.ubicacion, evaluacion and evaluacion.ubicacion)
        pedido.prioridad_vigente = calculo and calculo.prioridad_final
        pedido.tipo_vigente = evaluacion and evaluacion.tipo_principal
        pedido.puntaje_total = calculo and calculo.puntaje_total
        pedido.motivos_revision = [str(m) for m in resultado.motivos_revision]
        pedido.estado = (
            EstadoPedido.REQUIERE_REVISION if resultado.motivos_revision else EstadoPedido.PENDIENTE
        )
        pedido.save()

    def confirmar(self, pedido_id: int, responsable: str) -> Pedido:
        """Valida la recomendación vigente sin modificar la prioridad ni el tipo (9.1)."""
        responsable = _obligatorio(responsable, "El responsable es obligatorio")
        with transaction.atomic():
            pedido = _bloquear(pedido_id)
            if pedido.prioridad_vigente is None:
                raise ErrorOperacion(
                    "Este pedido no tiene prioridad recomendada; corregí prioridad y tipo"
                )
            _validar(pedido, responsable)
            pedido.save()
        return pedido

    def corregir(
        self, pedido_id: int, *, prioridad: Prioridad, tipo: str, motivo: str, responsable: str
    ) -> CorreccionManual:
        """Registra una corrección; la recomendación original queda intacta (9.2–9.6)."""
        motivo = _obligatorio(motivo, "El motivo es obligatorio")
        responsable = _obligatorio(responsable, "El responsable es obligatorio")
        prioridad = _prioridad(prioridad)
        if tipo not in self.config.nombres_tipos():
            raise ErrorOperacion(f"El tipo «{tipo}» no está en la lista de tipos configurados")
        with transaction.atomic():
            pedido = _bloquear(pedido_id)
            if (pedido.prioridad_vigente, pedido.tipo_vigente) == (prioridad, tipo):
                raise ErrorOperacion(
                    "La corrección no cambia la prioridad ni el tipo; para validarlos, confirmá"
                )
            correccion = CorreccionManual.objects.create(
                pedido=pedido,
                responsable=responsable,
                prioridad_anterior=pedido.prioridad_vigente,
                prioridad_nueva=prioridad,
                tipo_anterior=pedido.tipo_vigente,
                tipo_nuevo=tipo,
                motivo=motivo,
            )
            pedido.prioridad_vigente = prioridad
            pedido.tipo_vigente = tipo
            pedido.corregido = True
            _validar(pedido, responsable)
            pedido.save()
        return correccion

    def _registrar_en_log(self, pedido: Pedido, resultado: ResultadoDominio) -> None:
        # Sin el texto del pedido, para no volcar datos personales al log.
        prioridad = resultado.calculo.prioridad_final.name if resultado.calculo else "-"
        logger.info(
            "triage pedido_id=%s origen=%s intentos=%s duracion_ms=%s prioridad=%s",
            pedido.pk,
            resultado.origen,
            resultado.intentos_ia,
            resultado.duracion_ms,
            prioridad,
        )
        if resultado.duracion_ms > LIMITE_DURACION_MS:
            logger.warning(
                "El triage del pedido %s tardó %s ms, más que el objetivo de 10 s",
                pedido.pk,
                resultado.duracion_ms,
            )
