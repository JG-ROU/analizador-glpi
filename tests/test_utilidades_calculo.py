"""Períodos, estadísticas, días hábiles y filtros (RN-01 a RN-05)."""

from datetime import date, datetime

import pytest

from core import seguridad
from core.analisis import calendario as cal
from core.analisis import estadistica as est
from core.analisis import periodos as p
from core.analisis.filtros import Filtros, filtros_permitidos
from core.errores import ErrorPermiso

# --- Períodos (RN-01) ---

def test_semana_iso():
    semana = p.semana(2026, 39)
    assert (semana.inicio, semana.fin) == (datetime(2026, 9, 21), datetime(2026, 9, 28))
    assert semana.etiqueta == "Semana 39 de 2026 (21/09 – 27/09)"
    assert semana.codigo == "2026-W39"


def test_semana_iso_que_cruza_el_anio():
    semana = p.semana_de(date(2027, 1, 1))
    assert semana.codigo == "2026-W53"
    assert semana.inicio == datetime(2026, 12, 28)


def test_mes():
    mes = p.mes(2026, 12)
    assert (mes.inicio, mes.fin) == (datetime(2026, 12, 1), datetime(2027, 1, 1))
    assert mes.etiqueta == "Diciembre 2026" and mes.codigo == "2026-12"


def test_rango_incluye_ambos_dias():
    rango = p.rango(date(2026, 9, 1), date(2026, 9, 15))
    assert rango.contiene(datetime(2026, 9, 15, 23, 59))
    assert not rango.contiene(datetime(2026, 9, 16, 0, 0))
    assert rango.etiqueta == "01/09/2026 – 15/09/2026"
    with pytest.raises(ValueError):
        p.rango(date(2026, 9, 2), date(2026, 9, 1))


def test_limites_del_periodo():
    mes = p.mes(2026, 9)
    assert mes.contiene(datetime(2026, 9, 1, 0, 0))
    assert not mes.contiene(datetime(2026, 10, 1, 0, 0))
    assert not mes.contiene(datetime(2026, 8, 31, 23, 59))


@pytest.mark.parametrize(
    "periodo, anterior",
    [
        (p.semana(2026, 1), p.semana(2025, 52)),
        (p.mes(2026, 1), p.mes(2025, 12)),
        (p.mes(2026, 3), p.mes(2026, 2)),
        (p.rango(date(2026, 9, 11), date(2026, 9, 20)), p.rango(date(2026, 9, 1), date(2026, 9, 10))),
    ],
)
def test_periodo_anterior(periodo, anterior):
    assert periodo.anterior() == anterior


def test_corte_de_periodo_en_curso_y_terminado():
    ahora = datetime(2026, 9, 24, 10, 0)
    assert p.mes(2026, 9).corte(ahora) == ahora
    assert p.mes(2026, 8).corte(ahora) == datetime(2026, 9, 1)


def test_semanas_en_un_mes():
    semanas = p.semanas_en(p.mes(2026, 9))
    assert [s.codigo for s in semanas] == ["2026-W36", "2026-W37", "2026-W38", "2026-W39", "2026-W40"]


def test_ultimos_periodos():
    assert [m.codigo for m in p.ultimos(p.mes(2026, 2), 3)] == ["2025-12", "2026-01", "2026-02"]


# --- Estadística (RN-02, RN-04) ---

def test_mediana_y_p90_como_excel():
    valores = [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
    assert est.mediana(valores) == 5.5
    assert est.percentil(valores, 90) == 18.1  # PERCENTIL.INC(1..9;100 ; 0,9)
    assert est.promedio(valores) == 14.5


def test_valores_vacios_se_ignoran():
    assert est.mediana([None, 4, None, 2]) == 3
    assert est.mediana([]) is None and est.percentil([None], 90) is None


def test_resumen_con_muestra_pequena():
    resumen = est.resumir_tiempos([10.0, 20.0, None], muestra_minima=10)
    assert (resumen.cantidad, resumen.mediana, resumen.muestra_pequena) == (2, 15.0, True)
    grande = est.resumir_tiempos(range(10), muestra_minima=10)
    assert not grande.muestra_pequena


def test_porcentaje():
    assert est.porcentaje(1, 3) == 33.33
    assert est.porcentaje(5, 4) == 125.0
    assert est.porcentaje(3, 0) is None


# --- Días hábiles y festivos (RN-05) ---

def test_dias_habiles():
    festivos = {date(2026, 10, 12)}
    assert cal.es_habil(date(2026, 10, 9), festivos)  # viernes
    assert not cal.es_habil(date(2026, 10, 10), festivos)  # sábado
    assert not cal.es_habil(date(2026, 10, 12), festivos)  # festivo
    assert cal.dias_habiles_entre(date(2026, 10, 9), date(2026, 10, 16), festivos) == 4
    assert cal.sumar_dias_habiles(date(2026, 10, 9), 2, festivos) == date(2026, 10, 14)


def test_festivos_guardados(bd):
    with bd:
        bd.execute("INSERT INTO festivo (fecha, descripcion) VALUES ('2026-12-25', 'Navidad')")
    assert cal.festivos_guardados(bd) == {date(2026, 12, 25)}


@pytest.mark.parametrize("anio, pascua", [(2024, date(2024, 3, 31)), (2026, date(2026, 4, 5)),
                                          (2027, date(2027, 3, 28))])
def test_domingo_de_pascua(anio, pascua):
    assert cal.domingo_de_pascua(anio) == pascua


def test_festivos_colombia_2026():
    fechas = [f for f, _ in cal.festivos_colombia(2026)]
    assert fechas == [
        date(2026, 1, 1), date(2026, 1, 12), date(2026, 3, 23), date(2026, 4, 2),
        date(2026, 4, 3), date(2026, 5, 1), date(2026, 5, 18), date(2026, 6, 8),
        date(2026, 6, 15), date(2026, 6, 29), date(2026, 7, 20), date(2026, 8, 7),
        date(2026, 8, 17), date(2026, 10, 12), date(2026, 11, 2), date(2026, 11, 16),
        date(2026, 12, 8), date(2026, 12, 25),
    ]


# --- Filtros ---

def test_filtros_a_sql_parametrizado():
    texto, parametros = Filtros(
        tecnico_id=3, turno="Tarde", prioridades=(5, 6), estados=("ESCALADO",)
    ).sql()
    assert texto == (
        " AND t.tecnico_principal_id = ? AND t.turno_apertura = ?"
        " AND t.prioridad_nivel IN (?, ?) AND t.estado_codigo IN (?)"
    )
    assert parametros == [3, "Tarde", 5, 6, "ESCALADO"]
    assert Filtros().sql() == ("", [])


def test_valores_maliciosos_quedan_como_parametros():
    texto, parametros = Filtros(turno="x'; DROP TABLE ticket; --").sql("k")
    assert "DROP" not in texto and parametros == ["x'; DROP TABLE ticket; --"]


def crear_consulta(bd, coordinador, nombre, tecnico):
    with bd:
        tecnico_id = bd.execute(
            "INSERT INTO tecnico (nombre_glpi, nombre_mostrar, creado_en) VALUES (?, ?, '2026-09-24')",
            (tecnico, tecnico),
        ).lastrowid
    usuario = seguridad.crear_usuario(
        bd, coordinador, nombre=nombre, perfil=seguridad.CONSULTA, pin="1111", tecnico_id=tecnico_id
    )
    return seguridad.iniciar_sesion(bd, usuario, "1111"), tecnico_id


def test_filtros_permitidos_por_perfil(bd, coordinador):
    sesion, propio = crear_consulta(bd, coordinador, "Uno", "Tecnico 01")
    _, ajeno = crear_consulta(bd, coordinador, "Dos", "Tecnico 02")
    assert filtros_permitidos(coordinador, Filtros(tecnico_id=ajeno)).tecnico_id == ajeno
    assert filtros_permitidos(sesion, Filtros()).tecnico_id is None  # indicadores del equipo
    assert filtros_permitidos(sesion, Filtros(tecnico_id=propio, turno="Tarde")) == Filtros(
        tecnico_id=propio, turno="Tarde"
    )
    with pytest.raises(ErrorPermiso):
        filtros_permitidos(sesion, Filtros(tecnico_id=ajeno))
