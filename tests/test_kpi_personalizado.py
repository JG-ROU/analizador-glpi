"""KPIs creados por el usuario (KPI-00) y CA-09."""

from datetime import datetime

import pytest

import generador_glpi as gen
from ayudas import importar_diario, ticket
from core import clasificacion as cl
from core import configuracion as cfg
from core import historial
from core.analisis import condiciones, periodos, semaforo
from core.analisis.kpis import CalculadoraKPI
from core.errores import ErrorPermiso, ErrorValidacion

SEPTIEMBRE = periodos.mes(2026, 9)
AHORA = datetime(2026, 10, 5, 12, 0)


def d(dia, hora=10):
    return datetime(2026, 9, dia, hora, 0)


@pytest.fixture
def datos(bd, coordinador, tmp_path):
    tickets = [
        ticket(1, d(1), "Tecnico 01", "Mediana", (d(1, 20), gen.RESUELTO)),    # REC sin causa, 10 h
        ticket(2, d(2), "Tecnico 01", "Mediana", (d(3), gen.RESUELTO)),        # REC con causa, 24 h
        ticket(3, d(3), "Tecnico 02", "Urgente", (d(3, 14), gen.RESUELTO)),    # REC sin causa, 4 h
        ticket(4, d(4), "Tecnico 02", "Urgente", (d(6), gen.RESUELTO)),        # APL sin causa, 48 h
        ticket(5, d(5), "Tecnico 02", "Baja"),                                 # sin clasificar
    ]
    importar_diario(bd, coordinador, tickets, d(1), d(6, 23), tmp_path)
    cl.clasificar(bd, coordinador, [1, 3], {cl.CATEGORIA: "REC-01"})
    cl.clasificar(bd, coordinador, [2], {cl.CATEGORIA: "REC-03.1", cl.CAUSA: "CAU-02"})
    cl.clasificar(bd, coordinador, [4], {cl.CATEGORIA: "APL-01"})
    return bd


REC_SIN_CAUSA = {
    "nombre": "% tickets REC sin CAUSA",
    "tipo_calculo": "PORCENTAJE",
    "numerador": [{"campo": "tiene_causa", "valor": False}],
    "denominador": [{"campo": "familia", "valores": ["REC"]}],
    "direccion": "MENOR_MEJOR", "umbral_verde": 10, "umbral_amarillo": 30,
}


def test_ca09_kpi_rec_sin_causa_en_el_dashboard(datos, coordinador):
    codigo = cfg.guardar_kpi_personalizado(datos, coordinador, REC_SIN_CAUSA)
    assert codigo == "KPI-U01"
    visibles = CalculadoraKPI(datos, coordinador, AHORA).calcular_visibles(SEPTIEMBRE)
    kpi = next(r for r in visibles if r.codigo == codigo)
    assert (kpi.numerador, kpi.denominador, kpi.valor) == (2, 3, 66.67)
    assert kpi.semaforo == semaforo.ROJO and kpi.unidad == "%"
    assert historial.consultar(datos, entidad="kpi_definicion")[0]["accion"] == "CREAR"


def test_vista_previa_sin_guardar(datos, coordinador):
    definicion = cfg.definicion_kpi(REC_SIN_CAUSA)
    kpi = CalculadoraKPI(datos, coordinador, AHORA).calcular_definicion(definicion, SEPTIEMBRE)
    assert kpi.valor == 66.67
    assert datos.execute("SELECT COUNT(*) FROM kpi_definicion WHERE predefinido = 0").fetchone()[0] == 0


def test_conteo_y_tiempos(datos, coordinador):
    calc = CalculadoraKPI(datos, coordinador, AHORA)
    conteo = calc.calcular_definicion(cfg.definicion_kpi({
        "nombre": "Urgentes", "tipo_calculo": "CONTEO", "numerador": [{"campo": "prioridad", "valores": [4]}],
    }), SEPTIEMBRE)
    assert conteo.valor == 2
    mediana = calc.calcular_definicion(cfg.definicion_kpi({
        "nombre": "Mediana REC", "tipo_calculo": "MEDIANA_TIEMPO", "campo_tiempo": "horas_resolucion",
        "numerador": [{"campo": "categoria_prefijo", "valor": "REC"}],
    }), SEPTIEMBRE)
    assert (mediana.valor, mediana.cantidad, mediana.unidad, mediana.aproximado) == (10.0, 3, "horas", True)
    rango = calc.calcular_definicion(cfg.definicion_kpi({
        "nombre": "Rápidos", "tipo_calculo": "CONTEO",
        "numerador": [{"campo": "horas_resolucion", "min": 0, "max": 12}],
    }), SEPTIEMBRE)
    assert rango.valor == 2


def test_modificar_y_eliminar(datos, coordinador):
    codigo = cfg.guardar_kpi_personalizado(datos, coordinador, REC_SIN_CAUSA)
    cfg.guardar_kpi_personalizado(datos, coordinador, {**REC_SIN_CAUSA, "umbral_verde": 70, "umbral_amarillo": 80},
                                  codigo)
    kpi = CalculadoraKPI(datos, coordinador, AHORA).calcular(codigo, SEPTIEMBRE)
    assert kpi.semaforo == semaforo.VERDE
    assert {r["campo"] for r in historial.consultar(datos, entidad="kpi_definicion", entidad_id=codigo)} >= {
        "umbral_verde", "umbral_amarillo"}
    assert cfg.guardar_kpi_personalizado(datos, coordinador, REC_SIN_CAUSA) == "KPI-U02"
    cfg.eliminar_kpi_personalizado(datos, coordinador, codigo)
    assert datos.execute("SELECT COUNT(*) FROM kpi_definicion WHERE codigo = ?", (codigo,)).fetchone()[0] == 0


def test_predefinidos_no_se_editan_ni_eliminan_asi(datos, coordinador):
    with pytest.raises(ErrorValidacion, match="predefinidos"):
        cfg.eliminar_kpi_personalizado(datos, coordinador, "KPI-04")
    with pytest.raises(ErrorValidacion, match="predefinidos"):
        cfg.guardar_kpi_personalizado(datos, coordinador, REC_SIN_CAUSA, "KPI-04")


def test_consulta_no_crea_kpis(datos, consulta):
    with pytest.raises(ErrorPermiso):
        cfg.guardar_kpi_personalizado(datos, consulta, REC_SIN_CAUSA)


@pytest.mark.parametrize(
    "cambios, mensaje",
    [
        ({"nombre": " "}, "nombre"),
        ({"tipo_calculo": "OTRO"}, "tipo de cálculo"),
        ({"tipo_calculo": "MEDIANA_TIEMPO"}, "campo de tiempo"),
        ({"numerador": [{"campo": "inventado", "valores": [1]}]}, "desconocida"),
        ({"numerador": [{"campo": "familia", "valores": []}]}, "al menos un valor"),
        ({"numerador": [{"campo": "horas_resolucion"}]}, "mínimo o un máximo"),
        ({"umbral_verde": 30, "umbral_amarillo": 10}, "menor es mejor"),
    ],
)
def test_definiciones_invalidas(cambios, mensaje):
    with pytest.raises(ErrorValidacion, match=mensaje):
        cfg.definicion_kpi({**REC_SIN_CAUSA, **cambios})


def test_condiciones_a_sql_parametrizado():
    texto, valores = condiciones.a_sql([
        {"campo": "familia", "valores": ["REC", "x'); DROP TABLE ticket; --"]},
        {"campo": "es_p1", "valor": False},
        {"campo": "categoria_prefijo", "valor": "REC_0%"},
    ])
    assert "DROP" not in texto and "NOT (t.es_p1 = 1)" in texto
    assert valores == ["REC", "x'); DROP TABLE ticket; --", "REC\\_0\\%%"]


def test_describir_condiciones():
    texto = condiciones.describir(REC_SIN_CAUSA["numerador"] + REC_SIN_CAUSA["denominador"])
    assert texto == "Tiene causa: No y Familia de categoría: REC"
    assert condiciones.describir([]) == "Todos los tickets"
