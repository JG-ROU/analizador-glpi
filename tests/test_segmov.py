"""SEGMOV (REP-08, CA-12)."""

from datetime import datetime

import pytest

from ayudas import importar_diario, ticket
from core import clasificacion as cl
from core import historial
from core.analisis import periodos, segmov
from core.errores import ErrorPermiso, ErrorValidacion


@pytest.mark.parametrize(
    "total, casos, esperado",
    [
        (100, {"A": 5, "B": 3, "C": 2}, {"A": 50.0, "B": 30.0, "C": 20.0}),
        (100, {"A": 1, "B": 1, "C": 1}, {"A": 33.4, "B": 33.3, "C": 33.3}),
        (10, {"A": 1, "B": 1, "C": 1, "D": 3}, {"A": 1.7, "B": 1.7, "C": 1.6, "D": 5.0}),
        (100, {"A": 0, "B": 0}, {"A": 0.0, "B": 0.0}),
        (7, {"A": 2, "B": 0, "C": 1}, {"A": 4.7, "B": 0.0, "C": 2.3}),
    ],
)
def test_ca12_distribucion_con_ajuste_de_residuo(total, casos, esperado):
    resultado = segmov.distribuir(total, casos)
    assert sum(resultado.values()) == pytest.approx(total if sum(casos.values()) else 0)
    assert round(sum(resultado.values()), 1) == (total if sum(casos.values()) else 0)
    assert sorted(resultado.values()) == sorted(esperado.values())
    for clave, n in casos.items():
        if n == 0:
            assert resultado[clave] == 0.0


def test_ca12_suma_exacta_con_1_1_1():
    resultado = segmov.distribuir(100, {"A": 1, "B": 1, "C": 1})
    assert round(sum(resultado.values()), 1) == 100.0
    assert sorted(resultado.values()) == [33.3, 33.3, 33.4]


def d(dia, hora=10):
    return datetime(2026, 9, dia, hora, 0)


def test_calcular_y_guardar_con_estaciones_reales(bd, coordinador, tmp_path):
    tickets = [ticket(i, d(i), "Tecnico 01", "Baja") for i in range(1, 11)]
    importar_diario(bd, coordinador, tickets, d(1), d(10, 23), tmp_path)
    norte = cl.guardar_estacion(bd, coordinador, nombre="Norte")
    sur = cl.guardar_estacion(bd, coordinador, nombre="Sur")
    oeste = cl.guardar_estacion(bd, coordinador, nombre="Oeste")
    excluida = cl.guardar_estacion(bd, coordinador, nombre="Excluida", incluir_segmov=False)
    cl.clasificar(bd, coordinador, [1, 2, 3, 4, 5], {cl.ESTACION: norte})
    cl.clasificar(bd, coordinador, [6, 7, 8], {cl.ESTACION: sur})
    cl.clasificar(bd, coordinador, [9, 10], {cl.ESTACION: oeste})
    cl.clasificar(bd, coordinador, [], {cl.ESTACION: excluida})
    septiembre = periodos.mes(2026, 9)
    filas = segmov.guardar(bd, coordinador, septiembre, 100)
    assert [(f.estacion, f.casos, f.horas) for f in filas] == [("Norte", 5, 50.0), ("Oeste", 2, 20.0), ("Sur", 3, 30.0)]
    guardadas = bd.execute("SELECT COUNT(*), SUM(horas_asignadas) FROM segmov WHERE periodo = '2026-09'").fetchone()
    assert tuple(guardadas) == (3, 100.0)
    segmov.guardar(bd, coordinador, septiembre, 120)
    assert bd.execute("SELECT SUM(horas_asignadas) FROM segmov WHERE periodo = '2026-09'").fetchone()[0] == 120.0
    assert historial.consultar(bd, entidad="segmov")[0]["valor_nuevo"] == "120 horas entre 3 estaciones"
    assert list(segmov.tabla(filas)["% de casos"]) == [50.0, 20.0, 30.0]


def test_validaciones(bd, coordinador, consulta):
    with pytest.raises(ErrorValidacion, match="por mes"):
        segmov.calcular(bd, periodos.semana(2026, 38), 100)
    with pytest.raises(ErrorValidacion, match="total de horas"):
        segmov.calcular(bd, periodos.mes(2026, 9), -5)
    with pytest.raises(ErrorPermiso):
        segmov.guardar(bd, consulta, periodos.mes(2026, 9), 100)
