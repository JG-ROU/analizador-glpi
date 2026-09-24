"""Carga incremental, historial de cambios y eventos (IMP-03, IMP-06, CA-04)."""

import sqlite3
from datetime import datetime

import pytest

import generador_glpi as gen
from core.errores import ErrorAplicacion, ErrorPermiso, ErrorValidacion
from core.fuentes.fuente_csv import FuenteCSV
from core.importacion import carga
from core.importacion import eventos as ev
from core.importacion import mapeo as m
from core.importacion import validacion as v
from core.turnos import interpretar_franja

FRANJAS = (
    interpretar_franja("Mañana", "06:00-14:00"),
    interpretar_franja("Tarde", "14:00-22:00"),
    interpretar_franja("Nocturno", "22:00-06:00"),
)
CORTES = [datetime(2026, 9, dia, 23, 0) for dia in range(1, 9)]


def d(dia, hora, minuto=0):
    return datetime(2026, 9, dia, hora, minuto)


def escenario():
    """Tickets con una historia conocida, para verificar a mano cada evento."""
    base = dict(entidad=gen.ENTIDAD_BASE, autor="Autor 001", ubicacion="Depto > Filial > Cliente > Estación")
    escalado_dos_veces = gen.TicketFicticio(
        1001, "Escalado dos veces", apertura=d(1, 8), cambios=[
            gen.Cambio(d(1, 8), estado=gen.ASIGNADO, tecnicos=("Tecnico 01",), prioridad="Urgente"),
            gen.Cambio(d(2, 9), estado=gen.ESCALADO),
            gen.Cambio(d(3, 10), estado=gen.ASIGNADO),
            gen.Cambio(d(4, 11), estado=gen.ESCALADO),
            gen.Cambio(d(5, 12), estado=gen.RESUELTO),
            gen.Cambio(d(6, 13), estado=gen.CERRADO),
            gen.Cambio(d(7, 14), estado=gen.ASIGNADO),
            gen.Cambio(d(8, 15), estado=gen.RESUELTO),
        ], **base,
    )
    reasignado = gen.TicketFicticio(
        1002, "Reasignado", apertura=d(1, 15), cambios=[
            gen.Cambio(d(1, 15), estado=gen.ASIGNADO, tecnicos=("Tecnico 01",), prioridad="Mediana"),
            gen.Cambio(d(2, 12), tecnicos=("Tecnico 02", "Tecnico 03")),
            gen.Cambio(d(3, 9), prioridad="Urgente"),
        ], **base,
    )
    cerrado_antes = gen.TicketFicticio(
        1003, "P1 cerrado antes de la primera importación", apertura=d(1, 2), cambios=[
            gen.Cambio(d(1, 2), estado=gen.ASIGNADO, tecnicos=("Tecnico 04",), prioridad="Mayor"),
            gen.Cambio(d(1, 5), estado=gen.RESUELTO),
            gen.Cambio(d(1, 20), estado=gen.CERRADO),
        ], **base,
    )
    abierto_despues = gen.TicketFicticio(
        1004, "Abierto el día 5", apertura=d(5, 22, 30), cambios=[
            gen.Cambio(d(5, 22, 30), estado=gen.NUEVO, tecnicos=(), prioridad="Baja"),
        ], **base,
    )
    return [escalado_dos_veces, reasignado, cerrado_antes, abierto_despues]


@pytest.fixture
def perfil(bd, coordinador):
    propuesto = m.PerfilImportacion(
        nombre="Exportación GLPI", separador=";", codificacion="utf-8",
        formato_fecha="%d-%m-%Y %H:%M", mapeo=m.Mapeo(columnas=m.proponer_columnas(gen.ENCABEZADOS)),
    )
    return m.guardar_perfil(bd, coordinador, propuesto, gen.ENCABEZADOS)


@pytest.fixture
def importar(bd, coordinador, perfil, tmp_path):
    def _importar(ruta, sesion=coordinador, progreso=None):
        fuente = FuenteCSV(ruta)
        return carga.importar(
            bd, sesion, archivo=ruta.name, hash_archivo=fuente.hash, perfil=perfil,
            validacion=v.validar(fuente.obtener_tickets(), perfil), franjas=FRANJAS,
            carpeta_respaldos=tmp_path / "respaldos", retencion_respaldos=30, progreso=progreso,
        )
    return _importar


@pytest.fixture
def exportar(tmp_path):
    def _exportar(tickets, corte, errores=0):
        filas = gen.filas_en(tickets, corte)
        if errores:
            filas = gen.inyectar_errores(filas, errores)
        return gen.escribir_csv(filas, tmp_path / "csv" / f"glpi_{corte:%Y%m%d_%H%M}.csv")
    return _exportar


def ticket(bd, id_glpi):
    return bd.execute("SELECT * FROM ticket WHERE id_glpi = ?", (id_glpi,)).fetchone()


def eventos(bd, id_glpi):
    return [
        (f["tipo"], f["fecha_evento"], f["origen"])
        for f in bd.execute(
            "SELECT tipo, fecha_evento, origen FROM ticket_evento WHERE ticket_id = ? ORDER BY id",
            (id_glpi,),
        )
    ]


def cambios(bd, id_glpi):
    return [
        (f["campo"], f["valor_anterior"], f["valor_nuevo"])
        for f in bd.execute(
            "SELECT campo, valor_anterior, valor_nuevo FROM ticket_cambio WHERE ticket_id = ? ORDER BY id",
            (id_glpi,),
        )
    ]


def contar(bd, tabla):
    return bd.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


# --- Primera importación ---

def test_primera_importacion(bd, importar, exportar):
    resumen = importar(exportar(escenario(), CORTES[0]))
    assert (resumen.nuevos, resumen.actualizados, resumen.sin_cambios) == (3, 0, 0)
    assert resumen.respaldo is not None and resumen.respaldo.exists()

    registro = bd.execute("SELECT * FROM importacion").fetchone()
    assert (registro["filas_leidas"], registro["filas_validas"], registro["filas_error"]) == (3, 3, 0)
    assert registro["fecha_min"] == "2026-09-01 02:00:00"
    assert registro["fecha_max"] == "2026-09-01 15:00:00"
    assert registro["perfil_id"] is not None and registro["usuario_id"] is not None

    uno = ticket(bd, 1001)
    assert (uno["estado_codigo"], uno["prioridad_nivel"], uno["turno_apertura"]) == (
        "EN_CURSO_ASIGNADO", 4, "Mañana",
    )
    assert uno["tipo_caso"] == "GESTION" and uno["fecha_solucion"] is None


def test_ticket_ya_cerrado_la_primera_vez(bd, importar, exportar):
    importar(exportar(escenario(), CORTES[0]))
    assert eventos(bd, 1003) == [
        ("SOLUCION", "2026-09-01 20:00:00", "PRIMERA_VEZ"),
        ("CIERRE", "2026-09-01 20:00:00", "PRIMERA_VEZ"),
    ]
    tres = ticket(bd, 1003)
    assert (tres["es_p1"], tres["tipo_caso"]) == (1, "CRITICO_P1")
    assert tres["fecha_solucion"] == tres["fecha_cierre"] == "2026-09-01 20:00:00"
    assert tres["horas_resolucion"] == 18.0  # aproximada: solución = última actualización


def test_tecnicos_se_crean_y_se_asocian(bd, importar, exportar):
    importar(exportar(escenario(), CORTES[1]))
    nombres = {f[0] for f in bd.execute("SELECT nombre_glpi FROM tecnico")}
    assert nombres == {"Tecnico 01", "Tecnico 02", "Tecnico 03", "Tecnico 04"}
    asignados = bd.execute(
        "SELECT t.nombre_glpi, tt.orden FROM ticket_tecnico tt JOIN tecnico t ON t.id = tt.tecnico_id "
        "WHERE tt.ticket_id = 1002 ORDER BY tt.orden"
    ).fetchall()
    assert [tuple(a) for a in asignados] == [("Tecnico 02", 1), ("Tecnico 03", 2)]
    principal = bd.execute(
        "SELECT t.nombre_glpi FROM ticket k JOIN tecnico t ON t.id = k.tecnico_principal_id "
        "WHERE k.id_glpi = 1002"
    ).fetchone()[0]
    assert principal == "Tecnico 02"


# --- CA-04 ---

def test_ca04_reimportar_el_mismo_archivo_no_duplica(bd, importar, exportar):
    ruta = exportar(escenario(), CORTES[0])
    importar(ruta)
    antes = {t: contar(bd, t) for t in ("importacion", "ticket", "ticket_evento", "ticket_cambio")}
    with pytest.raises(ErrorValidacion, match="ya se importó"):
        importar(ruta)
    assert {t: contar(bd, t) for t in antes} == antes


def test_ca04_version_posterior_registra_cambios_eventos_y_reapertura(bd, importar, exportar):
    tickets = escenario()
    for corte in CORTES[:6]:
        importar(exportar(tickets, corte))
    uno = ticket(bd, 1001)
    assert (uno["estado_codigo"], uno["fecha_solucion"], uno["fecha_cierre"]) == (
        "CERRADO", "2026-09-05 12:00:00", "2026-09-06 13:00:00",
    )
    assert uno["horas_resolucion"] == 100.0 and uno["horas_hasta_cierre"] == 125.0

    for corte in CORTES[6:]:
        importar(exportar(tickets, corte))
    assert eventos(bd, 1001) == [
        ("ESCALAMIENTO", "2026-09-02 09:00:00", "TRANSICION"),
        ("SALIDA_ESCALADO", "2026-09-03 10:00:00", "TRANSICION"),
        ("ESCALAMIENTO", "2026-09-04 11:00:00", "TRANSICION"),
        ("SALIDA_ESCALADO", "2026-09-05 12:00:00", "TRANSICION"),
        ("SOLUCION", "2026-09-05 12:00:00", "TRANSICION"),
        ("CIERRE", "2026-09-06 13:00:00", "TRANSICION"),
        ("REAPERTURA", "2026-09-07 14:00:00", "TRANSICION"),
        ("SOLUCION", "2026-09-08 15:00:00", "TRANSICION"),
    ]
    assert [c for c in cambios(bd, 1001) if c[0] == "estado"] == [
        ("estado", "En curso (asignada)", "Escalado"),
        ("estado", "Escalado", "En curso (asignada)"),
        ("estado", "En curso (asignada)", "Escalado"),
        ("estado", "Escalado", "Resueltas"),
        ("estado", "Resueltas", "Cerrado"),
        ("estado", "Cerrado", "En curso (asignada)"),
        ("estado", "En curso (asignada)", "Resueltas"),
    ]
    uno = ticket(bd, 1001)
    assert uno["tipo_caso"] == "ESCALAMIENTO"
    assert (uno["fecha_solucion"], uno["fecha_cierre"]) == ("2026-09-08 15:00:00", None)
    assert uno["horas_resolucion"] == 175.0


def test_ca04_cambios_de_tecnico_y_prioridad(bd, importar, exportar):
    tickets = escenario()
    for corte in CORTES[:3]:
        importar(exportar(tickets, corte))
    assert cambios(bd, 1002) == [
        ("tecnico", "Tecnico 01", "Tecnico 02, Tecnico 03"),
        ("prioridad", "Mediana", "Urgente"),
    ]
    assert ticket(bd, 1002)["prioridad_nivel"] == 4


def test_archivo_antiguo_no_hace_retroceder_los_datos(bd, importar, exportar):
    tickets = escenario()
    importar(exportar(tickets, CORTES[4]))
    resumen = importar(exportar(tickets, CORTES[1]))
    assert resumen.omitidos_por_antiguos == 2
    assert ticket(bd, 1001)["estado_codigo"] == "RESUELTO"
    assert ticket(bd, 1002)["prioridad"] == "Urgente"
    assert contar(bd, "ticket_cambio") == 0


def test_tickets_sin_cambios_y_tickets_nuevos(bd, importar, exportar):
    tickets = escenario()
    importar(exportar(tickets, CORTES[3]))
    resumen = importar(exportar(tickets, datetime(2026, 9, 5, 23, 0)))
    # 1001 cambió (se resolvió el día 5); 1002 y 1003 no cambian desde el día 3; 1004 es nuevo
    assert (resumen.nuevos, resumen.actualizados, resumen.sin_cambios) == (1, 1, 2)
    importacion_id = resumen.importacion_id
    assert ticket(bd, 1003)["ultima_importacion_id"] == importacion_id
    assert ticket(bd, 1004)["primera_importacion_id"] == importacion_id


def test_tipo_de_caso_corregido_a_mano_no_se_pisa(bd, importar, exportar):
    tickets = escenario()
    importar(exportar(tickets, CORTES[0]))
    with bd:
        bd.execute("UPDATE ticket SET tipo_caso = 'SOLICITUD', tipo_caso_origen = 'MANUAL' WHERE id_glpi = 1001")
    importar(exportar(tickets, CORTES[1]))
    uno = ticket(bd, 1001)
    assert (uno["tipo_caso"], uno["escalado"]) == ("SOLICITUD", 1)


# --- Errores, permisos y transacción ---

def test_filas_con_error_no_se_cargan(bd, importar, exportar):
    resumen = importar(exportar(escenario(), CORTES[7], errores=6))
    assert resumen.filas_error == 6
    assert contar(bd, "ticket") == 4
    assert bd.execute("SELECT filas_error FROM importacion").fetchone()[0] == 6


def test_solo_el_coordinador_importa(bd, importar, exportar, consulta):
    with pytest.raises(ErrorPermiso):
        importar(exportar(escenario(), CORTES[0]), sesion=consulta)
    assert contar(bd, "importacion") == 0


def test_si_falla_la_carga_no_queda_nada(bd, importar, exportar, monkeypatch):
    original = carga._Cargador._insertar
    llamadas = []

    def falla_en_el_tercero(self, *args):
        llamadas.append(1)
        if len(llamadas) == 3:
            raise sqlite3.OperationalError("disco lleno")
        return original(self, *args)

    monkeypatch.setattr(carga._Cargador, "_insertar", falla_en_el_tercero)
    with pytest.raises(ErrorAplicacion, match="no se guardó ningún dato"):
        importar(exportar(escenario(), CORTES[0]))
    for tabla in ("importacion", "ticket", "ticket_tecnico", "ticket_evento", "tecnico"):
        assert contar(bd, tabla) == 0, tabla


def test_importacion_queda_en_el_historial(bd, importar, exportar):
    importar(exportar(escenario(), CORTES[0]))
    registro = bd.execute("SELECT * FROM historial WHERE entidad = 'importacion'").fetchone()
    assert registro["accion"] == "IMPORTAR"
    assert "3 nuevos" in registro["nota"]


def test_avance_de_la_carga(importar, exportar):
    avances = []
    importar(exportar(escenario(), CORTES[7]), progreso=lambda hechas, total: avances.append((hechas, total)))
    assert avances[-1] == (4, 4)


# --- Secuencia generada (coherencia general) ---

def test_secuencia_diaria_generada_es_coherente(bd, importar, tmp_path):
    tickets = gen.generar_tickets(300, datetime(2026, 7, 1), datetime(2026, 9, 10), semilla=21)
    cortes = gen.cortes_diarios(datetime(2026, 9, 23, 23, 59), 20)
    for corte in cortes:
        ruta = gen.escribir_csv(gen.filas_en(tickets, corte), tmp_path / "seq" / f"{corte:%Y%m%d}.csv")
        importar(ruta)
    detectados = dict(bd.execute(
        "SELECT ticket_id, COUNT(*) FROM ticket_evento WHERE tipo = 'ESCALAMIENTO' GROUP BY ticket_id"
    ).fetchall())
    assert sum(detectados.values()) > 0
    ultimo = cortes[-1]
    for t in tickets:
        foto = t.foto(ultimo)
        if foto is None:
            continue
        guardado = ticket(bd, t.id_glpi)
        assert guardado["estado"] == foto["estado"]
        # Nunca se detectan más escalamientos que los que ocurrieron
        assert detectados.get(t.id_glpi, 0) <= t.veces_en(gen.ESCALADO)
    assert contar(bd, "importacion") == 20


# --- Eventos (función pura) ---

@pytest.mark.parametrize(
    "anterior, nuevo, esperado",
    [
        (None, "EN_CURSO_ASIGNADO", []),
        (None, "ESCALADO", ["ESCALAMIENTO"]),
        (None, "RESUELTO", ["SOLUCION"]),
        (None, "CERRADO", ["SOLUCION", "CIERRE"]),
        ("EN_CURSO_ASIGNADO", "ESCALADO", ["ESCALAMIENTO"]),
        ("ESCALADO", "EN_ESPERA", ["SALIDA_ESCALADO"]),
        ("ESCALADO", "CERRADO", ["SALIDA_ESCALADO", "SOLUCION", "CIERRE"]),
        ("EN_ESPERA", "RESUELTO", ["SOLUCION"]),
        ("RESUELTO", "CERRADO", ["CIERRE"]),
        ("CERRADO", "EN_CURSO_ASIGNADO", ["REAPERTURA"]),
        ("RESUELTO", "ESCALADO", ["REAPERTURA", "ESCALAMIENTO"]),
        ("EN_CURSO_ASIGNADO", "EN_ESPERA", []),
    ],
)
def test_eventos_de_transicion(anterior, nuevo, esperado):
    assert ev.eventos_de_transicion(anterior, nuevo) == esperado


def test_aplicar_eventos():
    vacio = ev.FechasAproximadas(None, None)
    resuelto = ev.aplicar_eventos(vacio, ["SOLUCION"], d(5, 12))
    assert resuelto == ev.FechasAproximadas(d(5, 12), None)
    cerrado = ev.aplicar_eventos(resuelto, ["CIERRE"], d(6, 13))
    assert cerrado == ev.FechasAproximadas(d(5, 12), d(6, 13))
    assert ev.aplicar_eventos(cerrado, ["REAPERTURA"], d(7, 14)) == vacio
