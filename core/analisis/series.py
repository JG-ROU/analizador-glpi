"""Series de datos para los gráficos del dashboard (PAN-03) y de los reportes.

Los períodos largos se agrupan por mes en lugar de por semana, para que los
gráficos sigan siendo legibles.
"""

import sqlite3
from dataclasses import dataclass

from core.analisis import periodos as p
from core.analisis import responsables
from core.analisis.filtros import Filtros, filtros_permitidos
from core.analisis.kpis import NOMBRE_PRIORIDAD, CalculadoraKPI, ResultadoKPI
from core.errores import ErrorPermiso

MAXIMO_SEMANAS = 26
NOMBRE_ESTADO = {
    "NUEVO": "Nuevo",
    "EN_CURSO_ASIGNADO": "En curso (asignado)",
    "EN_CURSO_PLANIFICADO": "En curso (planificado)",
    "EN_ESPERA": "En espera",
    "ESCALADO": "Escalado",
    "RESUELTO": "Resuelto",
    "CERRADO": "Cerrado",
}


@dataclass(frozen=True)
class PuntoSerie:
    etiqueta: str
    valores: dict[str, float | None]


@dataclass(frozen=True)
class Brecha:
    codigo: str
    nombre: str
    valor: float
    objetivo: float
    tipo_objetivo: str  # "Meta" o "Umbral verde"
    semaforo: str


def subperiodos(periodo: p.Periodo) -> list[p.Periodo]:
    """Semanas del período; si son demasiadas, meses."""
    semanas = p.semanas_en(periodo)
    if len(semanas) <= MAXIMO_SEMANAS:
        return semanas
    meses = []
    actual = p.mes_de(periodo.inicio)
    while actual.inicio < periodo.fin:
        meses.append(actual)
        actual = p.mes_de(actual.fin)
    return meses


def _etiqueta_corta(periodo: p.Periodo) -> str:
    if periodo.granularidad == p.SEMANA:
        return f"S{periodo.inicio.isocalendar()[1]:02d}"
    return f"{p.MESES[periodo.inicio.month - 1][:3].capitalize()} {periodo.inicio:%y}"


def recibidos_resueltos(calc: CalculadoraKPI, periodo: p.Periodo, filtros: Filtros = Filtros()) -> list[PuntoSerie]:
    return [
        PuntoSerie(_etiqueta_corta(sub), {
            "Recibidos": calc.calcular("KPI-01", sub, filtros, comparar=False).valor,
            "Resueltos": calc.calcular("KPI-02", sub, filtros, comparar=False).valor,
        })
        for sub in subperiodos(periodo)
    ]


def backlog(calc: CalculadoraKPI, periodo: p.Periodo, filtros: Filtros = Filtros()) -> list[PuntoSerie]:
    """Backlog al cierre de cada semana (o mes) del período."""
    return [
        PuntoSerie(_etiqueta_corta(sub), {
            "Backlog": calc.calcular("KPI-03", sub, filtros, comparar=False).valor,
        })
        for sub in subperiodos(periodo)
    ]


def abiertos_por_prioridad(calc: CalculadoraKPI, periodo: p.Periodo, filtros: Filtros = Filtros()) -> dict[str, int]:
    detalle = calc.calcular("KPI-03", periodo, filtros, comparar=False).detalle
    return {d["prioridad"]: d["abiertos"] for d in detalle}


def recibidos_por_estado(
    conexion: sqlite3.Connection, calc: CalculadoraKPI, periodo: p.Periodo, filtros: Filtros = Filtros()
) -> dict[str, int]:
    """Tickets recibidos en el período según su estado actual."""
    condicion, valores = filtros_permitidos(calc.sesion, filtros).sql("t")
    filas = conexion.execute(
        "SELECT t.estado_codigo, COUNT(*) FROM ticket t WHERE t.fecha_apertura >= ? "
        "AND t.fecha_apertura < ?" + condicion + " GROUP BY t.estado_codigo",
        [periodo.inicio.isoformat(sep=" "), periodo.fin.isoformat(sep=" "), *valores],
    ).fetchall()
    conteo = dict(filas)
    return {nombre: conteo.get(codigo, 0) for codigo, nombre in NOMBRE_ESTADO.items()}


def carga_por_tecnico(
    conexion: sqlite3.Connection, calc: CalculadoraKPI, periodo: p.Periodo, filtros: Filtros = Filtros()
) -> dict[str, dict[str, int]]:
    """Abiertos al corte por técnico y prioridad. Consulta: solo el propio técnico;
    jefatura sin técnico: nada (CA-08)."""
    try:
        visibles = {t["id"]: t["nombre_mostrar"] for t in responsables.tecnicos_visibles(conexion, calc.sesion)}
    except ErrorPermiso:
        return {}
    carga: dict[str, dict[str, int]] = {}
    for ticket in calc.abiertos_al_corte(filtros, periodo.corte(calc.ahora)):
        nombre = visibles.get(ticket["tecnico_principal_id"])
        if nombre is None:
            continue
        prioridad = NOMBRE_PRIORIDAD[ticket["prioridad_nivel"]]
        carga.setdefault(nombre, {})
        carga[nombre][prioridad] = carga[nombre].get(prioridad, 0) + 1
    return dict(sorted(carga.items()))


def brechas(resultados: list[ResultadoKPI], definiciones: dict) -> list[Brecha]:
    """Valor frente a la meta (o al umbral verde si no hay meta) de los KPIs en %."""
    lista = []
    for r in resultados:
        if r.valor is None or r.unidad != "%":
            continue
        definicion = definiciones[r.codigo]
        if r.meta is not None:
            objetivo, tipo = r.meta, "Meta"
        elif definicion["umbral_verde"] is not None:
            objetivo, tipo = definicion["umbral_verde"], "Umbral verde"
        else:
            continue
        lista.append(Brecha(r.codigo, r.nombre, r.valor, objetivo, tipo, r.semaforo))
    return lista
