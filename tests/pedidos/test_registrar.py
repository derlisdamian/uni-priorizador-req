"""Registro de pedidos con priorización automática (`ServicioPedidos.registrar`)."""

import logging
from decimal import Decimal

import pytest

from pedidos import services
from pedidos.models import NO_INFORMADO, EstadoPedido, Pedido, ResultadoTriage
from pedidos.services import DatosPedido, ServicioPedidos, construir_evaluadores
from tests.pedidos.conftest import EvaluadorFalso, evaluacion, falla
from triage.config import Umbral
from triage.evaluadores.cache import EvaluadorConCache
from triage.evaluadores.gemini import EvaluadorGemini
from triage.evaluadores.palabras_clave import EvaluadorPalabrasClave
from triage.schemas import Canal, MotivoRevision, Prioridad
from triage.scoring import calcular_prioridad

pytestmark = pytest.mark.django_db

TEXTO = "Hay cables expuestos en el pasillo del bloque B. Avisar a ana@uni.edu.ar o al 351 555 1234"


def datos(**cambios) -> DatosPedido:
    valores = {
        "canal": Canal.FORMULARIO,
        "texto": TEXTO,
        "dependencia": "Facultad de Ingeniería",
        "ubicacion": "Pasillo del bloque B",
        "contacto": "Ana Pérez, ana@uni.edu.ar",
    }
    return DatosPedido(**(valores | cambios))


class TestRegistroPorFormulario:
    def test_persiste_el_pedido_y_su_resultado(self, construir_servicio, config):
        pedido = construir_servicio().registrar(datos())

        pedido.refresh_from_db()
        assert pedido.canal == Canal.FORMULARIO
        assert pedido.texto_original == TEXTO
        assert pedido.contacto == "Ana Pérez, ana@uni.edu.ar"
        assert pedido.dependencia == "Facultad de Ingeniería"
        assert pedido.ubicacion == "Pasillo del bloque B"
        assert pedido.prioridad_vigente == Prioridad.P1
        assert pedido.tipo_vigente == "Electricidad"
        assert pedido.puntaje_total is not None
        assert pedido.estado == EstadoPedido.PENDIENTE
        assert pedido.motivos_revision == []

        resultado = pedido.resultado
        assert resultado.origen == "ia"
        assert resultado.modelo == "gemini-falso"
        assert resultado.prioridad_final == Prioridad.P1
        assert resultado.puntaje_total == pedido.puntaje_total
        assert resultado.tipo_principal == "Electricidad"
        assert resultado.evaluacion["criterios"]["riesgo_personas"]["puntaje"] == 3
        assert resultado.confianza == Decimal("0.90")
        assert resultado.version_config == config.version
        assert resultado.justificacion_texto.startswith("Prioridad P1")
        assert resultado.justificacion["es_respaldo"] is False
        assert resultado.reglas_aplicadas[0]["id"] == "riesgo_personas_grave"
        assert resultado.intentos_ia == 1
        assert resultado.motivos_revision == []

    def test_guarda_el_codigo_de_ejemplo_solo_si_se_informa(self, construir_servicio):
        servicio = construir_servicio()
        assert servicio.registrar(datos()).codigo_ejemplo is None
        pedido = servicio.registrar(datos(codigo_ejemplo="EJ-01"))
        pedido.refresh_from_db()
        assert pedido.codigo_ejemplo == "EJ-01"

    def test_no_envia_el_contacto_y_anonimiza_el_texto(self, construir_servicio, config):
        principal = EvaluadorFalso(evaluacion(config), modelo="gemini-falso")
        construir_servicio(principal=principal).registrar(datos())

        enviada = principal.entradas[0]
        assert "contacto" not in enviada.model_dump()
        serializada = enviada.model_dump_json()
        assert "ana@uni.edu.ar" not in serializada
        assert "Ana Pérez" not in serializada
        assert "351 555 1234" not in serializada
        assert "[correo]" in enviada.texto and "[telefono]" in enviada.texto

    def test_los_motivos_de_revision_dejan_el_pedido_en_revision(self, construir_servicio, config):
        principal = EvaluadorFalso(evaluacion(config, confianza=0.59), modelo="gemini-falso")
        pedido = construir_servicio(principal=principal).registrar(datos())

        pedido.refresh_from_db()
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert pedido.motivos_revision == [MotivoRevision.CONFIANZA_BAJA]
        assert pedido.resultado.confianza == Decimal("0.59")


class TestRegistroPorTextoLibre:
    def test_resuelve_la_dependencia_y_la_ubicacion_extraidas(self, construir_servicio):
        pedido = construir_servicio().registrar(
            datos(canal=Canal.TEXTO_LIBRE, dependencia=None, ubicacion=None, contacto=None)
        )
        pedido.refresh_from_db()
        assert pedido.canal == Canal.TEXTO_LIBRE
        assert pedido.texto_original == TEXTO
        assert pedido.dependencia == "Facultad de Ingeniería"
        assert pedido.ubicacion == "Pasillo del bloque B"
        assert pedido.estado == EstadoPedido.PENDIENTE

    def test_marca_no_informado_lo_que_no_se_pudo_extraer(self, construir_servicio, config):
        principal = EvaluadorFalso(
            evaluacion(config, dependencia=None, ubicacion=None), modelo="gemini-falso"
        )
        pedido = construir_servicio(principal=principal).registrar(
            datos(canal=Canal.TEXTO_LIBRE, dependencia="  ", ubicacion=None, contacto=None)
        )
        pedido.refresh_from_db()
        assert pedido.dependencia == NO_INFORMADO
        assert pedido.ubicacion == NO_INFORMADO
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert pedido.motivos_revision == [
            MotivoRevision.DEPENDENCIA_NO_INFORMADA,
            MotivoRevision.UBICACION_NO_INFORMADA,
        ]

    def test_la_dependencia_informada_tiene_precedencia(self, construir_servicio):
        pedido = construir_servicio().registrar(
            datos(canal=Canal.TEXTO_LIBRE, dependencia="Rectorado")
        )
        pedido.refresh_from_db()
        assert pedido.dependencia == "Rectorado"


class TestFallas:
    def test_respaldo_queda_en_revision_sin_modelo(self, construir_servicio, config):
        principal = EvaluadorFalso(falla(), modelo="gemini-falso")
        respaldo = EvaluadorFalso(evaluacion(config, confianza=0.0), nombre="palabras_clave")
        pedido = construir_servicio(principal=principal, respaldo=respaldo).registrar(datos())

        pedido.refresh_from_db()
        assert pedido.resultado.origen == "respaldo"
        assert pedido.resultado.modelo is None
        assert pedido.resultado.intentos_ia == 2
        assert len(pedido.resultado.errores) == 2
        assert pedido.prioridad_vigente == Prioridad.P1
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert MotivoRevision.CLASIFICACION_RESPALDO in pedido.motivos_revision

    def test_sin_clasificacion_queda_registrado_sin_prioridad(self, construir_servicio):
        principal = EvaluadorFalso(falla(), modelo="gemini-falso")
        pedido = construir_servicio(principal=principal).registrar(datos())

        pedido.refresh_from_db()
        assert pedido.resultado.origen == "sin_clasificacion"
        assert pedido.resultado.evaluacion is None
        assert pedido.resultado.prioridad_final is None
        assert pedido.prioridad_vigente is None
        assert pedido.tipo_vigente is None
        assert pedido.puntaje_total is None
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert MotivoRevision.SIN_CLASIFICACION in pedido.motivos_revision

    def test_persiste_el_pedido_si_el_triage_lanza_una_excepcion(
        self, construir_servicio, monkeypatch, caplog
    ):
        def explotar(*args, **kwargs):
            raise RuntimeError("falla inesperada")

        monkeypatch.setattr(services, "triar_pedido", explotar)
        pedido = construir_servicio().registrar(datos())

        pedido = Pedido.objects.get(pk=pedido.pk)
        assert pedido.texto_original == TEXTO
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert pedido.motivos_revision == [MotivoRevision.SIN_CLASIFICACION]
        assert pedido.prioridad_vigente is None
        assert not ResultadoTriage.objects.filter(pedido=pedido).exists()
        assert "no pudo priorizarse" in caplog.text

    def test_persiste_el_pedido_si_falla_guardar_el_resultado(
        self, construir_servicio, monkeypatch
    ):
        def explotar(self, *args, **kwargs):
            raise RuntimeError("se cayó la base")

        monkeypatch.setattr(ResultadoTriage, "save", explotar)
        pedido = construir_servicio().registrar(datos())

        pedido.refresh_from_db()
        assert pedido.estado == EstadoPedido.REQUIERE_REVISION
        assert pedido.motivos_revision == [MotivoRevision.SIN_CLASIFICACION]
        assert pedido.prioridad_vigente is None  # la actualización se revirtió junto al resultado
        assert pedido.tipo_vigente is None


class TestRegistroEnElLog:
    def test_registra_cada_triage_sin_el_texto(self, construir_servicio, caplog):
        caplog.set_level(logging.INFO, logger="triage")
        pedido = construir_servicio().registrar(datos())

        registros = [r for r in caplog.records if r.name == "triage"]
        assert len(registros) == 1
        mensaje = registros[0].getMessage()
        assert f"pedido_id={pedido.pk}" in mensaje
        assert "origen=ia" in mensaje
        assert "prioridad=P1" in mensaje
        assert "cables" not in mensaje and "ana@uni.edu.ar" not in mensaje
        assert registros[0].levelno == logging.INFO

    def test_advierte_si_supera_los_10_segundos(self, construir_servicio, monkeypatch, caplog):
        original = services.triar_pedido

        def lento(*args, **kwargs):
            return original(*args, **kwargs).model_copy(update={"duracion_ms": 10_001})

        monkeypatch.setattr(services, "triar_pedido", lento)
        construir_servicio().registrar(datos())

        advertencias = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert advertencias and "10 s" in advertencias[0].getMessage()


def test_cambiar_la_configuracion_no_cambia_las_prioridades_registradas(construir_servicio, config):
    puntajes = {"impacto_academico": 1}
    umbrales_bajos = [
        Umbral(prioridad=Prioridad.P1, minimo=3),
        Umbral(prioridad=Prioridad.P2, minimo=2),
        Umbral(prioridad=Prioridad.P3, minimo=1),
    ]
    nueva = config.model_copy(update={"umbrales": umbrales_bajos, "version": "nueva0000000"})
    antes = calcular_prioridad({c: puntajes.get(c, 0) for c in config.claves_criterios()}, config)
    despues = calcular_prioridad({c: puntajes.get(c, 0) for c in nueva.claves_criterios()}, nueva)
    assert antes.prioridad_final != despues.prioridad_final

    def servicio(cfg):
        principal = EvaluadorFalso(evaluacion(cfg, puntajes=puntajes), modelo="gemini-falso")
        return construir_servicio(principal=principal, config_servicio=cfg)

    primero = servicio(config).registrar(datos())
    segundo = servicio(nueva).registrar(datos())

    primero.refresh_from_db()
    segundo.refresh_from_db()
    assert primero.prioridad_vigente == antes.prioridad_final
    assert primero.resultado.version_config == config.version
    assert segundo.prioridad_vigente == despues.prioridad_final
    assert segundo.resultado.version_config == "nueva0000000"


class TestConstruccionDeEvaluadores:
    def test_gemini_y_respaldo_sin_cache(self, config, settings):
        settings.GEMINI_API_KEY = ""
        settings.GEMINI_MODEL = "gemini-de-prueba"
        settings.TRIAGE_USAR_CACHE = False
        principal, respaldo = construir_evaluadores(config)
        assert isinstance(principal, EvaluadorGemini)
        assert principal.modelo == "gemini-de-prueba"
        assert isinstance(respaldo, EvaluadorPalabrasClave)

    def test_con_cache_activado(self, config, settings, tmp_path):
        settings.TRIAGE_USAR_CACHE = True
        settings.TRIAGE_CACHE_ARCHIVO = tmp_path / "evaluaciones.json"
        principal, _ = construir_evaluadores(config)
        assert isinstance(principal, EvaluadorConCache)
        assert principal.archivo == tmp_path / "evaluaciones.json"

    def test_los_comandos_pueden_forzar_el_uso_del_cache(self, config, settings, tmp_path):
        settings.TRIAGE_USAR_CACHE = False
        settings.TRIAGE_CACHE_ARCHIVO = tmp_path / "evaluaciones.json"
        principal, _ = construir_evaluadores(config, usar_cache=True)
        assert isinstance(principal, EvaluadorConCache)

    def test_los_comandos_pueden_refrescar_el_cache(self, config, settings, tmp_path):
        settings.TRIAGE_CACHE_ARCHIVO = tmp_path / "evaluaciones.json"
        principal, _ = construir_evaluadores(config, usar_cache=True, refrescar_cache=True)
        assert principal.refrescar is True

    def test_los_comandos_pueden_desactivar_el_cache(self, config, settings):
        settings.TRIAGE_USAR_CACHE = True
        principal, _ = construir_evaluadores(config, usar_cache=False)
        assert isinstance(principal, EvaluadorGemini)

    def test_el_servicio_por_defecto_usa_la_configuracion_del_proceso(self, settings):
        settings.GEMINI_API_KEY = ""
        settings.TRIAGE_USAR_CACHE = False
        servicio = ServicioPedidos.desde_settings()
        assert servicio.config.version
        # Sin API key la IA no está configurada: el pedido se clasifica con el respaldo.
        pedido = servicio.registrar(datos(texto="Se cortó la luz en el aula 12, hay chispas"))
        pedido.refresh_from_db()
        assert pedido.resultado.origen in {"respaldo", "sin_clasificacion"}
        assert pedido.resultado.intentos_ia == 0

    def test_los_evaluadores_son_inyectables(self, config):
        principal = EvaluadorFalso(evaluacion(config), modelo="gemini-falso")
        respaldo = EvaluadorFalso(evaluacion(config))
        servicio = ServicioPedidos.desde_settings(construir=lambda cfg: (principal, respaldo))
        servicio.registrar(datos())
        assert len(principal.entradas) == 1
