"""Métricas por técnico para la pantalla Responsables (PAN-07, sin calidad) y REP-03.

Se usan las mismas fórmulas del motor de KPIs, filtradas por técnico principal.
El número de tickets es informativo (carga), no una calificación (spec 07).
Los resueltos sin cerrar dependen del visto bueno del autor: son informativos.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from core import seguridad
from core.analisis.filtros import Filtros
from core.analisis.kpis import CalculadoraKPI
from core.analisis.periodos import Periodo, semanas_en
from core.importacion import eventos as ev
from core.seguridad import Sesion


@dataclass
class MetricasTecnico:
    tecnico_id: int
    nombre: str
    turno: str | None
    abiertos: int
    abiertos_por_prioridad: dict[str, int] = field(default_factory=dict)
    atendidos: int = 0
    soluciones: int = 0
    escalamientos: int = 0
    tasa_escalamiento: float | None = None
    mediana_resolucion: float | None = None
    p90_resolucion: float | None = None
    sla: float | None = None
    sin_cerrar: float | None = None
    sin_cerrar_cantidad: int = 0
    reaperturas: int = 0
    sin_actualizar: int = 0
    documentacion: float | None = None  # KPI-14 del técnico (Fase 3)
    muestra_pequena: bool = True


def tecnicos_visibles(conexion: sqlite3.Connection, sesion: Sesion) -> list[sqlite3.Row]:
    """Coordinador: técnicos activos. Consulta: solo el propio (RNF-07, CA-08)."""
    if sesion.es_coordinador:
        return conexion.execute(
            "SELECT id, nombre_mostrar, turno FROM tecnico WHERE activo = 1 ORDER BY nombre_mostrar"
        ).fetchall()
    propio = seguridad.tecnico_permitido(sesion, None)
    return conexion.execute(
        "SELECT id, nombre_mostrar, turno FROM tecnico WHERE id = ?", (propio,)
    ).fetchall()


def metricas(
    conexion: sqlite3.Connection,
    sesion: Sesion,
    periodo: Periodo,
    tecnico_id: int | None = None,
    ahora: datetime | None = None,
) -> list[MetricasTecnico]:
    """Métricas del período para un técnico o para todos los visibles por la sesión."""
    if tecnico_id is not None:
        seguridad.tecnico_permitido(sesion, tecnico_id)
        tecnicos = [t for t in tecnicos_visibles(conexion, sesion) if t["id"] == tecnico_id]
        if not tecnicos:
            tecnicos = conexion.execute(
                "SELECT id, nombre_mostrar, turno FROM tecnico WHERE id = ?", (tecnico_id,)
            ).fetchall()
    else:
        tecnicos = tecnicos_visibles(conexion, sesion)
    calc = CalculadoraKPI(conexion, sesion, ahora)
    return [_metricas_de(calc, periodo, fila) for fila in tecnicos]


def _metricas_de(calc: CalculadoraKPI, periodo: Periodo, tecnico: sqlite3.Row) -> MetricasTecnico:
    filtros = Filtros(tecnico_id=tecnico["id"])

    def kpi(codigo):
        return calc.calcular(codigo, periodo, filtros, comparar=False)

    backlog = kpi("KPI-03")
    gestion = kpi("KPI-05")
    resolucion = kpi("KPI-06")
    sin_cerrar = kpi("KPI-08")
    atendidos = kpi("KPI-02")
    return MetricasTecnico(
        tecnico_id=tecnico["id"],
        nombre=tecnico["nombre_mostrar"],
        turno=tecnico["turno"],
        abiertos=int(backlog.valor or 0),
        abiertos_por_prioridad={d["prioridad"]: d["abiertos"] for d in backlog.detalle if d["abiertos"]},
        atendidos=int(atendidos.valor or 0),
        soluciones=gestion.detalle[0]["soluciones"],
        escalamientos=gestion.detalle[0]["escalamientos"],
        tasa_escalamiento=gestion.valor,
        mediana_resolucion=resolucion.valor,
        p90_resolucion=resolucion.p90,
        sla=kpi("KPI-07").valor,
        sin_cerrar=sin_cerrar.valor,
        sin_cerrar_cantidad=int(sin_cerrar.numerador or 0),
        reaperturas=calc.contar_eventos(ev.REAPERTURA, periodo, filtros),
        sin_actualizar=int(kpi("KPI-16").numerador or 0),
        documentacion=kpi("KPI-14").valor,
        muestra_pequena=atendidos.muestra_pequena,
    )


def atendidos_por_semana(
    conexion: sqlite3.Connection,
    sesion: Sesion,
    tecnico_id: int,
    periodo: Periodo,
    ahora: datetime | None = None,
) -> list[tuple[Periodo, int]]:
    """Tickets resueltos por el técnico en cada semana ISO que toca el período."""
    seguridad.tecnico_permitido(sesion, tecnico_id)
    calc = CalculadoraKPI(conexion, sesion, ahora)
    filtros = Filtros(tecnico_id=tecnico_id)
    return [
        (semana, calc.contar_eventos(ev.SOLUCION, semana, filtros, distintos=True))
        for semana in semanas_en(periodo)
    ]
