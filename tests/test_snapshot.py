"""Snapshot de KPIs y tendencias."""

from datetime import datetime

import generador_glpi as gen
from ayudas import importar_diario, ticket
from core import clasificacion as cl
from core import historial
from core.analisis import periodos, snapshot
from core.analisis.kpis import CalculadoraKPI


def d(mes, dia, hora=10):
    return datetime(2026, mes, dia, hora, 0)


def preparar(bd, coordinador, tmp_path):
    tickets = [
        ticket(1, d(7, 5), "Tecnico 01", "Baja", (d(7, 6), gen.RESUELTO)),
        ticket(2, d(8, 5), "Tecnico 01", "Baja", (d(8, 6), gen.ESCALADO)),
        ticket(3, d(8, 7), "Tecnico 02", "Baja", (d(8, 8), gen.RESUELTO)),
        ticket(4, d(9, 3), "Tecnico 02", "Baja"),
    ]
    importar_diario(bd, coordinador, tickets, d(7, 5), d(9, 3, 23), tmp_path)
    norte = cl.guardar_estacion(bd, coordinador, nombre="Norte", cliente="Cliente A")
    cl.clasificar(bd, coordinador, [2, 3], {cl.ESTACION: norte, cl.CATEGORIA: "REC-01"})


def valor(bd, periodo, kpi, dimension_tipo="GLOBAL", dimension_valor="TODOS"):
    fila = bd.execute(
        "SELECT valor FROM snapshot WHERE periodo = ? AND kpi_codigo = ? AND dimension_tipo = ? AND dimension_valor = ?",
        (periodo, kpi, dimension_tipo, dimension_valor),
    ).fetchone()
    return fila[0] if fila else "no existe"


def test_generar_mes_con_dimensiones(bd, coordinador, tmp_path):
    preparar(bd, coordinador, tmp_path)
    agosto = periodos.mes(2026, 8)
    guardados = snapshot.generar(bd, agosto, coordinador.usuario_id, ahora=d(9, 20))
    assert guardados > 0
    esperado = CalculadoraKPI(bd, coordinador, d(9, 20)).calcular("KPI-04", agosto, comparar=False).valor
    assert valor(bd, "2026-08", "KPI-04") == esperado == 100.0
    assert valor(bd, "2026-08", "KPI-01", "CLIENTE", "Cliente A") == 2
    assert valor(bd, "2026-08", "KPI-01", "FAMILIA", "REC") == 2
    tecnico = bd.execute("SELECT id FROM tecnico WHERE nombre_glpi = 'Tecnico 02'").fetchone()[0]
    assert valor(bd, "2026-08", "KPI-01", "TECNICO", str(tecnico)) == 1


def test_regenerar_reemplaza_y_queda_en_historial(bd, coordinador, tmp_path):
    preparar(bd, coordinador, tmp_path)
    agosto = periodos.mes(2026, 8)
    primero = snapshot.generar(bd, agosto, coordinador.usuario_id, ahora=d(9, 20))
    segundo = snapshot.generar(bd, agosto, coordinador.usuario_id, ahora=d(9, 21))
    assert primero == segundo
    assert bd.execute("SELECT COUNT(*) FROM snapshot WHERE periodo = '2026-08'").fetchone()[0] == segundo
    acciones = [r["accion"] for r in historial.consultar(bd, entidad="snapshot")]
    assert acciones[:2] == ["REGENERAR", "GENERAR"]


def test_pendientes_y_generacion_automatica(bd, coordinador, tmp_path):
    preparar(bd, coordinador, tmp_path)
    ahora = d(9, 24)
    assert [p.codigo for p in snapshot.pendientes(bd, ahora)] == ["2026-08", "2026-W38"]
    assert snapshot.generar_pendientes(bd, ahora) == ["2026-08", "2026-W38"]
    assert snapshot.generar_pendientes(bd, ahora) == []


def test_sin_tickets_no_genera(bd):
    assert snapshot.generar_pendientes(bd, d(9, 24)) == []


def test_tendencia(bd, coordinador, tmp_path):
    preparar(bd, coordinador, tmp_path)
    for mes in (7, 8, 9):
        snapshot.generar(bd, periodos.mes(2026, mes), ahora=d(9, 24))
    puntos = snapshot.tendencia(bd, "KPI-01", cantidad=6)
    assert [(p.periodo, p.valor) for p in puntos] == [("2026-07", 1.0), ("2026-08", 2.0), ("2026-09", 1.0)]
    assert [p.periodo for p in snapshot.tendencia(bd, "KPI-01", cantidad=2)] == ["2026-08", "2026-09"]
