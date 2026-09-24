"""Análisis por estación (PAN-06) y por tipificación (PAN-08)."""

from datetime import datetime

import pytest

import generador_glpi as gen
from ayudas import importar_diario, ticket
from core import clasificacion as cl
from core.analisis import distribucion, periodos, hallazgos

SEPTIEMBRE = periodos.mes(2026, 9)


def d(mes, dia, hora=10):
    return datetime(2026, mes, dia, hora, 0)


@pytest.fixture
def datos(bd, coordinador, tmp_path):
    tickets = [
        ticket(1, d(9, 1), "Tecnico 01", "Baja", (d(9, 1, 20), gen.RESUELTO)),
        ticket(2, d(9, 2), "Tecnico 01", "Baja", (d(9, 3), gen.RESUELTO)),
        ticket(3, d(9, 3), "Tecnico 02", "Baja"),
        ticket(4, d(9, 4), "Tecnico 02", "Baja"),
        ticket(5, d(9, 5), "Tecnico 02", "Baja"),
        ticket(6, d(8, 5), "Tecnico 02", "Baja"),
    ]
    importar_diario(bd, coordinador, tickets, d(8, 5), d(9, 5, 23), tmp_path)
    norte = cl.guardar_estacion(bd, coordinador, nombre="Norte", cliente="Cliente A")
    sur = cl.guardar_estacion(bd, coordinador, nombre="Sur", cliente="Cliente B")
    cl.clasificar(bd, coordinador, [1, 2, 3, 6], {cl.ESTACION: norte, cl.CATEGORIA: "REC-01"})
    cl.clasificar(bd, coordinador, [4], {cl.ESTACION: sur, cl.CATEGORIA: "APL-01"})
    return bd, norte, sur


def test_ranking_de_estaciones(datos, coordinador):
    bd, norte, sur = datos
    tabla = distribucion.ranking_estaciones(bd, coordinador, SEPTIEMBRE, ahora=d(10, 5))
    assert list(tabla["Estación"]) == ["Norte", "Sur", "(sin estación)"]
    norte_fila = tabla.iloc[0]
    # Abiertos al corte incluye el ticket 6 de agosto, que sigue abierto
    assert (norte_fila["Tickets"], norte_fila["Abiertos al corte"], norte_fila["Cliente"]) == (3, 2, "Cliente A")
    assert norte_fila["Mediana resolución (h) ≈"] == 17.0  # 10 h y 24 h
    assert tabla.iloc[2]["Tickets"] == 1


def test_detalle_de_estacion(datos, coordinador):
    bd, norte, _ = datos
    familias = distribucion.familias_de_estacion(bd, coordinador, norte, SEPTIEMBRE)
    assert familias == {"REC": 3}
    semanas = distribucion.tendencia_semanal_estacion(bd, coordinador, norte, SEPTIEMBRE)
    assert len(semanas) == 8 and sum(semanas.values()) == 3


def test_mapa_de_calor(datos, coordinador):
    bd, _, _ = datos
    mapa = distribucion.mapa_calor(bd, coordinador, SEPTIEMBRE)
    assert mapa.loc["Norte", "REC"] == 3 and mapa.loc["Sur", "APL"] == 1


def test_casos_repetidos_de_la_estacion(bd, coordinador, tmp_path):
    tickets = [ticket(10 + i, d(9, 14 + i), "Tecnico 01", "Baja") for i in range(3)]
    for t in tickets:
        t.titulo = "Falla de lector"
    importar_diario(bd, coordinador, tickets, d(9, 14), d(9, 16, 23), tmp_path)
    norte = cl.guardar_estacion(bd, coordinador, nombre="Norte")
    cl.clasificar(bd, coordinador, [10, 11, 12], {cl.ESTACION: norte})
    hallazgos.detectar(bd, ahora=d(9, 17))
    tabla = distribucion.casos_repetidos_de_estacion(bd, "Norte")
    assert list(tabla["Caso"]) == ["falla de lector"] and tabla.iloc[0]["Veces"] == 3


def test_tipificaciones(datos, coordinador):
    bd, _, _ = datos
    familias = distribucion.distribucion_familias(bd, coordinador, SEPTIEMBRE)
    assert familias == {"REC - Recaudo y conciliación": 3, "APL - Falla de aplicación": 1, "(sin categoría)": 1}
    categorias = distribucion.distribucion_categorias(bd, coordinador, SEPTIEMBRE)
    assert list(categorias["Código"]) == ["REC-01", "APL-01"] and categorias.iloc[0]["%"] == 75.0
    tendencia = distribucion.tendencia_familias(bd, coordinador, SEPTIEMBRE)
    assert tendencia.loc["2026-09", "REC"] == 3 and tendencia.loc["2026-08", "REC"] == 1
    crecen = distribucion.categorias_que_crecen(bd, coordinador, SEPTIEMBRE)
    rec = crecen[crecen["Código"] == "REC-01"].iloc[0]
    assert (rec["Tickets del mes"], rec["Promedio 3 meses"], rec["Variación %"]) == (3, 0.33, 800.0)
