"""Snapshot de KPIs y tendencias (spec 09).

Al importar datos de un mes o una semana ya cerrados (o con el botón «Generar
snapshot») se guarda el valor de cada KPI activo: global, por técnico, por
cliente y por familia. Las tendencias de 6 y 12 meses salen de esta tabla.
Regenerar un período reemplaza sus valores y queda en el historial.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from core import historial, reloj
from core.analisis import periodos
from core.analisis.filtros import Filtros
from core.analisis.hallazgos import SISTEMA
from core.analisis.kpis import CalculadoraKPI
from core.analisis.periodos import Periodo
from core.errores import ErrorValidacion

log = logging.getLogger(__name__)

GLOBAL, TECNICO, CLIENTE, FAMILIA = "GLOBAL", "TECNICO", "CLIENTE", "FAMILIA"
TODOS = "TODOS"
GRANULARIDAD = {periodos.MES: "MES", periodos.SEMANA: "SEMANA"}


@dataclass(frozen=True)
class PuntoTendencia:
    periodo: str
    valor: float | None


def _dimensiones(conexion: sqlite3.Connection) -> list[tuple[str, str, Filtros]]:
    dimensiones = [(GLOBAL, TODOS, Filtros())]
    dimensiones += [(TECNICO, str(f[0]), Filtros(tecnico_id=f[0]))
                    for f in conexion.execute("SELECT id FROM tecnico WHERE activo = 1")]
    dimensiones += [(CLIENTE, f[0], Filtros(clientes=(f[0],)))
                    for f in conexion.execute("SELECT DISTINCT cliente FROM estacion WHERE cliente IS NOT NULL")]
    dimensiones += [(FAMILIA, f[0], Filtros(familias=(f[0],)))
                    for f in conexion.execute(
                        "SELECT DISTINCT substr(categoria_codigo, 1, 3) FROM ticket_clasificacion "
                        "WHERE categoria_codigo IS NOT NULL")]
    return dimensiones


def generar(conexion: sqlite3.Connection, periodo: Periodo, usuario_id: int | None = None,
            ahora: datetime | None = None) -> int:
    """Calcula y guarda el snapshot del período (mes o semana). Devuelve cuántos valores guardó."""
    if periodo.granularidad not in GRANULARIDAD:
        raise ErrorValidacion("El snapshot se genera por mes o por semana.")
    ahora = ahora or reloj.ahora()
    calc = CalculadoraKPI(conexion, SISTEMA, ahora)
    filas = []
    for dimension_tipo, dimension_valor, filtros in _dimensiones(conexion):
        for codigo in calc.definiciones:
            resultado = calc.calcular(codigo, periodo, filtros, comparar=False)
            filas.append((periodo.codigo, GRANULARIDAD[periodo.granularidad], codigo, dimension_tipo,
                          dimension_valor, resultado.valor, ahora.isoformat(sep=" ")))
    with conexion:
        existia = conexion.execute(
            "SELECT COUNT(*) FROM snapshot WHERE periodo = ? AND granularidad = ?",
            (periodo.codigo, GRANULARIDAD[periodo.granularidad]),
        ).fetchone()[0]
        conexion.execute("DELETE FROM snapshot WHERE periodo = ? AND granularidad = ?",
                         (periodo.codigo, GRANULARIDAD[periodo.granularidad]))
        conexion.executemany("INSERT INTO snapshot VALUES (?, ?, ?, ?, ?, ?, ?)", filas)
        historial.registrar(conexion, entidad="snapshot", entidad_id=periodo.codigo,
                            accion="REGENERAR" if existia else "GENERAR", usuario_id=usuario_id,
                            valor_nuevo=f"{len(filas)} valores")
    log.info("Snapshot %s: %d valores", periodo.codigo, len(filas))
    return len(filas)


def pendientes(conexion: sqlite3.Connection, ahora: datetime | None = None) -> list[Periodo]:
    """Último mes y última semana cerrados que todavía no tienen snapshot."""
    ahora = ahora or reloj.ahora()
    candidatos = [periodos.mes_de(ahora).anterior(), periodos.semana_de(ahora).anterior()]
    faltan = []
    for periodo in candidatos:
        existe = conexion.execute(
            "SELECT 1 FROM snapshot WHERE periodo = ? AND granularidad = ? LIMIT 1",
            (periodo.codigo, GRANULARIDAD[periodo.granularidad]),
        ).fetchone()
        if existe is None:
            faltan.append(periodo)
    return faltan


def generar_pendientes(conexion: sqlite3.Connection, ahora: datetime | None = None) -> list[str]:
    """Genera los snapshots que falten (se llama después de cada importación)."""
    hay_tickets = conexion.execute("SELECT EXISTS (SELECT 1 FROM ticket)").fetchone()[0]
    if not hay_tickets:
        return []
    generados = []
    for periodo in pendientes(conexion, ahora):
        generar(conexion, periodo, ahora=ahora)
        generados.append(periodo.codigo)
    return generados


def tendencia(conexion: sqlite3.Connection, kpi_codigo: str, granularidad: str = "MES", cantidad: int = 6,
              dimension_tipo: str = GLOBAL, dimension_valor: str = TODOS) -> list[PuntoTendencia]:
    """Los últimos `cantidad` períodos guardados, del más antiguo al más reciente."""
    filas = conexion.execute(
        "SELECT periodo, valor FROM snapshot WHERE kpi_codigo = ? AND granularidad = ? AND dimension_tipo = ? "
        "AND dimension_valor = ? ORDER BY periodo DESC LIMIT ?",
        (kpi_codigo, granularidad, dimension_tipo, dimension_valor, cantidad),
    ).fetchall()
    return [PuntoTendencia(f["periodo"], f["valor"]) for f in reversed(filas)]
