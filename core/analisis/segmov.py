"""Distribución mensual de horas SEGMOV entre estaciones (REP-08, CA-12).

horas_estación = REDONDEAR(total × casos_estación / casos_total, 1). La diferencia
de redondeo se ajusta en la estación con mayor residuo, para que la suma sea
exactamente el total. Solo entran las estaciones marcadas «incluir en SEGMOV»;
los casos son los tickets del mes con esa estación asignada (IMP-07).
"""

import sqlite3
from dataclasses import dataclass

import pandas as pd

from core import historial, reloj, seguridad
from core.analisis.periodos import MES, Periodo
from core.errores import ErrorValidacion
from core.seguridad import Sesion

DECIMALES = 1


def distribuir(total_horas: float, casos: dict) -> dict:
    """Reparte `total_horas` en proporción a `casos` (clave → cantidad)."""
    total_casos = sum(casos.values())
    if total_casos == 0:
        return {clave: 0.0 for clave in casos}
    exactas = {clave: total_horas * n / total_casos for clave, n in casos.items()}
    redondeadas = {clave: round(valor, DECIMALES) for clave, valor in exactas.items()}
    diferencia = round(total_horas - sum(redondeadas.values()), DECIMALES)
    if diferencia:
        residuos = {clave: exactas[clave] - redondeadas[clave] for clave in casos if casos[clave]}
        # Si falta, se suma a la que más perdió al redondear; si sobra, se resta a la que más ganó
        elegida = max(residuos, key=residuos.get) if diferencia > 0 else min(residuos, key=residuos.get)
        redondeadas[elegida] = round(redondeadas[elegida] + diferencia, DECIMALES)
    return redondeadas


@dataclass(frozen=True)
class FilaSegmov:
    estacion_id: int
    estacion: str
    cliente: str | None
    casos: int
    horas: float


def calcular(conexion: sqlite3.Connection, periodo: Periodo, total_horas: float) -> list[FilaSegmov]:
    if periodo.granularidad != MES:
        raise ErrorValidacion("SEGMOV se calcula por mes: elija un mes como período.")
    if total_horas is None or total_horas < 0:
        raise ErrorValidacion("Indique el total de horas del mes (un número positivo).")
    filas = conexion.execute(
        "SELECT e.id, e.nombre, e.cliente, (SELECT COUNT(*) FROM ticket t JOIN ticket_clasificacion c "
        "ON c.ticket_id = t.id_glpi WHERE c.estacion_id = e.id AND t.fecha_apertura >= ? AND t.fecha_apertura < ?) "
        "AS casos FROM estacion e WHERE e.incluir_segmov = 1 AND e.activo = 1 ORDER BY e.nombre",
        (periodo.inicio.isoformat(sep=" "), periodo.fin.isoformat(sep=" ")),
    ).fetchall()
    horas = distribuir(total_horas, {f["id"]: f["casos"] for f in filas})
    return [FilaSegmov(f["id"], f["nombre"], f["cliente"], f["casos"], horas[f["id"]]) for f in filas]


def guardar(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo, total_horas: float) -> list[FilaSegmov]:
    """Calcula y guarda la distribución del mes (reemplaza la anterior), con historial."""
    seguridad.exigir_coordinador(sesion)
    filas = calcular(conexion, periodo, total_horas)
    ahora = reloj.ahora().isoformat(sep=" ")
    with conexion:
        conexion.execute("DELETE FROM segmov WHERE periodo = ?", (periodo.codigo,))
        conexion.executemany(
            "INSERT INTO segmov (periodo, estacion_id, casos, horas_asignadas, total_horas, generado_en, usuario_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(periodo.codigo, f.estacion_id, f.casos, f.horas, total_horas, ahora, sesion.usuario_id) for f in filas],
        )
        historial.registrar(conexion, entidad="segmov", entidad_id=periodo.codigo, accion="GENERAR",
                            usuario_id=sesion.usuario_id, valor_nuevo=f"{total_horas:g} horas entre {len(filas)} estaciones")
    return filas


def tabla(filas: list[FilaSegmov]) -> pd.DataFrame:
    total_casos = sum(f.casos for f in filas)
    return pd.DataFrame(
        [{"Estación": f.estacion, "Cliente": f.cliente or "—", "Casos": f.casos,
          "% de casos": round(f.casos / total_casos * 100, 2) if total_casos else 0.0, "Horas": f.horas}
         for f in filas],
        columns=["Estación", "Cliente", "Casos", "% de casos", "Horas"],
    )
