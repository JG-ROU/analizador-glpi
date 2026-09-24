"""Análisis por estación (PAN-06, REP-02) y por tipificación (PAN-08, REP-04).

Usan la clasificación manual (IMP-07): la estación y la categoría asignadas por
el coordinador. Los tickets sin clasificar se informan aparte.
"""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta

import pandas as pd

from core.analisis import periodos
from core.analisis.filtros import Filtros, filtros_permitidos
from core.analisis.kpis import CalculadoraKPI
from core.analisis.periodos import Periodo
from core.seguridad import Sesion

SIN_ESTACION = "(sin estación)"
SIN_CATEGORIA = "(sin categoría)"


def _iso(fecha: datetime) -> str:
    return fecha.isoformat(sep=" ")


def _recibidos(conexion, sesion, periodo: Periodo, filtros: Filtros) -> pd.DataFrame:
    """Tickets recibidos en el período con su clasificación."""
    condicion, valores = filtros_permitidos(sesion, filtros).sql("t")
    filas = conexion.execute(
        "SELECT t.id_glpi, t.fecha_apertura, t.fecha_solucion, t.horas_resolucion, t.estado_codigo, "
        "c.estacion_id, e.nombre AS estacion, e.cliente, c.categoria_codigo, "
        "substr(c.categoria_codigo, 1, 3) AS familia, k.nombre_mostrar AS tecnico "
        "FROM ticket t LEFT JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
        "LEFT JOIN estacion e ON e.id = c.estacion_id LEFT JOIN tecnico k ON k.id = t.tecnico_principal_id "
        "WHERE t.fecha_apertura >= ? AND t.fecha_apertura < ?" + condicion,
        [_iso(periodo.inicio), _iso(periodo.fin), *valores],
    ).fetchall()
    return pd.DataFrame([dict(f) for f in filas], columns=[
        "id_glpi", "fecha_apertura", "fecha_solucion", "horas_resolucion", "estado_codigo", "estacion_id",
        "estacion", "cliente", "categoria_codigo", "familia", "tecnico",
    ])


# --- Estaciones ---

def ranking_estaciones(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo,
                       filtros: Filtros = Filtros(), ahora: datetime | None = None) -> pd.DataFrame:
    """Por estación: volumen, reincidencia, mediana de resolución y abiertos al corte."""
    calc = CalculadoraKPI(conexion, sesion, ahora)
    estaciones = conexion.execute("SELECT id, nombre, cliente FROM estacion WHERE activo = 1").fetchall()
    filas = []
    for estacion in estaciones:
        propios = replace(filtros, estaciones=(estacion["id"],))
        recibidos = calc.calcular("KPI-01", periodo, propios, comparar=False)
        if not recibidos.valor:
            continue
        reincidencia = calc.calcular("KPI-11", periodo, propios, comparar=False)
        tiempo = calc.calcular("KPI-06", periodo, propios, comparar=False)
        abiertos = calc.calcular("KPI-03", periodo, propios, comparar=False)
        filas.append({
            "Estación": estacion["nombre"], "Cliente": estacion["cliente"] or "—",
            "Tickets": int(recibidos.valor), "Reincidencia %": reincidencia.valor,
            "Mediana resolución (h) ≈": tiempo.valor, "Abiertos al corte": int(abiertos.valor or 0),
            "_id": estacion["id"],
        })
    sin = _recibidos(conexion, sesion, periodo, filtros)
    sin_estacion = int(sin["estacion_id"].isna().sum())
    if sin_estacion:
        filas.append({"Estación": SIN_ESTACION, "Cliente": "—", "Tickets": sin_estacion, "Reincidencia %": None,
                      "Mediana resolución (h) ≈": None, "Abiertos al corte": None, "_id": None})
    tabla = pd.DataFrame(filas, columns=["Estación", "Cliente", "Tickets", "Reincidencia %",
                                         "Mediana resolución (h) ≈", "Abiertos al corte", "_id"])
    return tabla.sort_values("Tickets", ascending=False, kind="stable").reset_index(drop=True)


def tendencia_semanal_estacion(conexion, sesion, estacion_id: int, periodo: Periodo,
                               semanas: int = 8) -> dict[str, int]:
    """Tickets de la estación en las últimas `semanas` semanas que terminan en el período."""
    calc = CalculadoraKPI(conexion, sesion)
    lista = periodos.ultimos(periodos.semana_de(periodo.fin - timedelta(days=1)), semanas)
    filtros = Filtros(estaciones=(estacion_id,))
    return {f"S{s.inicio.isocalendar()[1]:02d}": int(calc.calcular("KPI-01", s, filtros, comparar=False).valor)
            for s in lista}


def familias_de_estacion(conexion, sesion, estacion_id: int, periodo: Periodo) -> dict[str, int]:
    datos = _recibidos(conexion, sesion, periodo, Filtros(estaciones=(estacion_id,)))
    return datos["familia"].fillna(SIN_CATEGORIA).value_counts().to_dict()


def casos_repetidos_de_estacion(conexion, nombre_estacion: str) -> pd.DataFrame:
    """Hallazgos HAL-01 abiertos de la estación."""
    filas = conexion.execute(
        "SELECT periodo, severidad, entidad_valor, datos_json FROM hallazgo WHERE regla = 'HAL-01' "
        "AND entidad_valor LIKE ? AND estado IN ('NUEVO', 'REVISADO') ORDER BY periodo DESC",
        (nombre_estacion + " | %",),
    ).fetchall()
    return pd.DataFrame(
        [{"Período": f["periodo"], "Severidad": f["severidad"], "Caso": f["entidad_valor"].split(" | ", 1)[1],
          "Veces": json.loads(f["datos_json"])["conteo"], "Tendencia": json.loads(f["datos_json"])["tendencia"],
          "Tickets": ", ".join(map(str, json.loads(f["datos_json"])["tickets"]))} for f in filas],
        columns=["Período", "Severidad", "Caso", "Veces", "Tendencia", "Tickets"],
    )


def mapa_calor(conexion, sesion, periodo: Periodo, filtros: Filtros = Filtros()) -> pd.DataFrame:
    """Tickets por estación (filas) y familia (columnas)."""
    datos = _recibidos(conexion, sesion, periodo, filtros).dropna(subset=["estacion"])
    if datos.empty:
        return pd.DataFrame()
    datos["familia"] = datos["familia"].fillna("—")
    return pd.crosstab(datos["estacion"], datos["familia"])


# --- Tipificaciones ---

def distribucion_familias(conexion, sesion, periodo: Periodo, filtros: Filtros = Filtros()) -> dict[str, int]:
    datos = _recibidos(conexion, sesion, periodo, filtros)
    nombres = dict(conexion.execute("SELECT DISTINCT familia, nivel1 FROM categoria").fetchall())
    conteo = datos["familia"].value_counts()
    resultado = {nombres.get(f, f): int(n) for f, n in conteo.items()}
    sin = int(datos["familia"].isna().sum())
    if sin:
        resultado[SIN_CATEGORIA] = sin
    return resultado


def distribucion_categorias(conexion, sesion, periodo: Periodo, filtros: Filtros = Filtros()) -> pd.DataFrame:
    datos = _recibidos(conexion, sesion, periodo, filtros).dropna(subset=["categoria_codigo"])
    nombres = dict(conexion.execute("SELECT codigo, COALESCE(nivel3, nivel2) FROM categoria").fetchall())
    conteo = datos["categoria_codigo"].value_counts()
    total = int(conteo.sum())
    return pd.DataFrame(
        [{"Código": c, "Categoría": nombres.get(c, c), "Familia": c[:3], "Tickets": int(n),
          "%": round(n / total * 100, 2)} for c, n in conteo.items()],
        columns=["Código", "Categoría", "Familia", "Tickets", "%"],
    )


def tendencia_familias(conexion, sesion, periodo: Periodo, meses: int = 6, filtros: Filtros = Filtros()) -> pd.DataFrame:
    """Tickets por familia en los últimos `meses` meses que terminan en el período (filas = meses)."""
    lista = periodos.ultimos(periodos.mes_de(periodo.fin - timedelta(days=1)), meses)
    filas = {}
    for mes in lista:
        datos = _recibidos(conexion, sesion, mes, filtros).dropna(subset=["familia"])
        filas[mes.codigo] = datos["familia"].value_counts().to_dict()
    return pd.DataFrame.from_dict(filas, orient="index").fillna(0).astype(int).sort_index()


def categorias_que_crecen(conexion, sesion, periodo: Periodo, filtros: Filtros = Filtros()) -> pd.DataFrame:
    """Variación de cada categoría en el mes del período frente al promedio de los 3 meses anteriores."""
    mes = periodos.mes_de(periodo.fin - timedelta(days=1))
    actual = _recibidos(conexion, sesion, mes, filtros)["categoria_codigo"].value_counts()
    anteriores = [_recibidos(conexion, sesion, m, filtros)["categoria_codigo"].value_counts()
                  for m in periodos.ultimos(mes.anterior(), 3)]
    filas = []
    for codigo, cantidad in actual.items():
        promedio = sum(a.get(codigo, 0) for a in anteriores) / 3
        variacion = None if promedio == 0 else round((cantidad - promedio) / promedio * 100, 1)
        filas.append({"Código": codigo, "Tickets del mes": int(cantidad), "Promedio 3 meses": round(promedio, 2),
                      "Variación %": variacion})
    tabla = pd.DataFrame(filas, columns=["Código", "Tickets del mes", "Promedio 3 meses", "Variación %"])
    return tabla.sort_values("Tickets del mes", ascending=False).reset_index(drop=True)
