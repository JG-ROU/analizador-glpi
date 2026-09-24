"""Métricas de calidad de soporte (spec 07: CAL-04 a CAL-08) y NOT-04.

Principios (spec 07): se mide para mejorar y conversar, no para castigar; nunca con
una sola métrica; los tiempos se comparan dentro de la misma categoría; cada técnico
se compara primero consigo mismo; el ranking lo ve solo el coordinador y excluye a
quien no alcanza la muestra mínima o está marcado «no incluir en ranking».
"""

import random
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from core import historial, parametros, reloj, seguridad
from core.analisis import estadistica as est
from core.analisis import periodos, responsables
from core.analisis.filtros import Filtros
from core.analisis.kpis import CalculadoraKPI
from core.analisis.periodos import Periodo
from core.errores import ErrorValidacion
from core.importacion import eventos as ev
from core.seguridad import Sesion

AVISO_RANKING = "Uso interno para conversaciones de desempeño; no publicar."


def _iso(fecha: datetime) -> str:
    return fecha.isoformat(sep=" ")


def _flecha(actual: float | None, referencia: float | None) -> tuple[str, float | None]:
    """Flecha ▲ ▼ = y % de variación de actual frente a la referencia."""
    if actual is None or referencia is None:
        return "—", None
    flecha = "▲" if actual > referencia else "▼" if actual < referencia else "="
    return flecha, (None if referencia == 0 else round((actual - referencia) / abs(referencia) * 100, 1))


# --- CAL-04: muestra semanal sugerida ---

@dataclass
class ElementoMuestra:
    ticket_id: int
    motivo: str


def _cerrados_en(conexion: sqlite3.Connection, semana: Periodo) -> list[sqlite3.Row]:
    return conexion.execute(
        "SELECT t.id_glpi, t.es_p1, t.tecnico_principal_id, t.fecha_apertura, t.fecha_cierre, "
        f"EXISTS (SELECT 1 FROM ticket_evento e WHERE e.ticket_id = t.id_glpi AND e.tipo = '{ev.ESCALAMIENTO}') AS escalado "
        "FROM ticket t WHERE t.fecha_cierre >= ? AND t.fecha_cierre < ? "
        "AND NOT EXISTS (SELECT 1 FROM evaluacion v WHERE v.ticket_id = t.id_glpi) ORDER BY t.id_glpi",
        (_iso(semana.inicio), _iso(semana.fin)),
    ).fetchall()


def proponer_muestra(conexion: sqlite3.Connection, semana: Periodo, ahora: datetime | None = None) -> list[ElementoMuestra]:
    """Tickets cerrados en `semana` para evaluar: todos los P1, los escalados de más de N días,
    al menos uno por técnico sin evaluaciones en las últimas 2 semanas y el resto al azar."""
    ahora = ahora or reloj.ahora()
    objetivo = parametros.entero(conexion, "tickets_auditoria_semana")
    dias_escalado = parametros.entero(conexion, "dias_escalado_muestra")
    candidatos = _cerrados_en(conexion, semana)
    elegidos: dict[int, str] = {}
    for fila in candidatos:
        if fila["es_p1"]:
            elegidos[fila["id_glpi"]] = "P1"
    for fila in candidatos:
        duracion = datetime.fromisoformat(fila["fecha_cierre"]) - datetime.fromisoformat(fila["fecha_apertura"])
        if fila["escalado"] and duracion > timedelta(days=dias_escalado) and fila["id_glpi"] not in elegidos:
            elegidos[fila["id_glpi"]] = f"Escalado más de {dias_escalado} días"
    # Al menos un ticket por técnico cada 2 semanas (se usa la semana anterior como respaldo)
    hace_dos_semanas = semana.fin - timedelta(days=14)
    evaluados = {f[0] for f in conexion.execute(
        "SELECT DISTINCT t.tecnico_principal_id FROM evaluacion v JOIN ticket t ON t.id_glpi = v.ticket_id "
        "WHERE v.fecha >= ?", (_iso(hace_dos_semanas),))}
    respaldo = candidatos + _cerrados_en(conexion, semana.anterior())
    cubiertos = {f["tecnico_principal_id"] for f in respaldo if f["id_glpi"] in elegidos} | evaluados
    for tecnico in [f[0] for f in conexion.execute("SELECT id FROM tecnico WHERE activo = 1 ORDER BY id")]:
        if tecnico in cubiertos:
            continue
        opcion = next((f for f in respaldo if f["tecnico_principal_id"] == tecnico and f["id_glpi"] not in elegidos), None)
        if opcion is not None:
            elegidos[opcion["id_glpi"]] = "Al menos uno por técnico cada 2 semanas"
            cubiertos.add(tecnico)
    resto = [f["id_glpi"] for f in candidatos if f["id_glpi"] not in elegidos]
    random.Random(semana.codigo).shuffle(resto)
    for ticket_id in resto[: max(0, objetivo - len(elegidos))]:
        elegidos[ticket_id] = "Al azar"
    return [ElementoMuestra(t, m) for t, m in elegidos.items()]


def muestra_de_semana(conexion: sqlite3.Connection, sesion: Sesion, semana: Periodo,
                      ahora: datetime | None = None) -> pd.DataFrame:
    """La muestra guardada de la semana; si no existe, se propone y se guarda."""
    seguridad.exigir_coordinador(sesion)
    existe = conexion.execute("SELECT 1 FROM muestra_auditoria WHERE semana = ? LIMIT 1", (semana.codigo,)).fetchone()
    if not existe:
        propuesta = proponer_muestra(conexion, semana, ahora)
        with conexion:
            conexion.executemany("INSERT INTO muestra_auditoria (semana, ticket_id, motivo) VALUES (?, ?, ?)",
                                 [(semana.codigo, e.ticket_id, e.motivo) for e in propuesta])
    filas = conexion.execute(
        "SELECT m.ticket_id, m.motivo, t.titulo, t.prioridad, k.nombre_mostrar AS tecnico, t.tipo_caso, "
        "v.resultado, v.porcentaje FROM muestra_auditoria m JOIN ticket t ON t.id_glpi = m.ticket_id "
        "LEFT JOIN tecnico k ON k.id = t.tecnico_principal_id "
        "LEFT JOIN evaluacion v ON v.ticket_id = m.ticket_id AND v.vigente = 1 "
        "WHERE m.semana = ? ORDER BY v.resultado IS NOT NULL, m.motivo, m.ticket_id", (semana.codigo,),
    ).fetchall()
    return pd.DataFrame([{
        "ID": f["ticket_id"], "Motivo": f["motivo"], "Título": f["titulo"], "Prioridad": f["prioridad"],
        "Técnico": f["tecnico"], "Evaluado": "Sí" if f["resultado"] else "No",
        "Resultado": f["resultado"] or "", "%": f["porcentaje"],
    } for f in filas], columns=["ID", "Motivo", "Título", "Prioridad", "Técnico", "Evaluado", "Resultado", "%"])


def agregar_a_muestra(conexion: sqlite3.Connection, sesion: Sesion, semana: Periodo, ticket_id: int) -> None:
    seguridad.exigir_coordinador(sesion)
    if conexion.execute("SELECT 1 FROM ticket WHERE id_glpi = ?", (ticket_id,)).fetchone() is None:
        raise ErrorValidacion(f"El ticket {ticket_id} no existe.")
    with conexion:
        conexion.execute("INSERT OR IGNORE INTO muestra_auditoria (semana, ticket_id, motivo) VALUES (?, ?, ?)",
                         (semana.codigo, ticket_id, "Agregado por el coordinador"))
        historial.registrar(conexion, entidad="muestra_auditoria", entidad_id=semana.codigo, accion="AGREGAR",
                            usuario_id=sesion.usuario_id, valor_nuevo=ticket_id)


def quitar_de_muestra(conexion: sqlite3.Connection, sesion: Sesion, semana: Periodo, ticket_id: int) -> None:
    seguridad.exigir_coordinador(sesion)
    with conexion:
        conexion.execute("DELETE FROM muestra_auditoria WHERE semana = ? AND ticket_id = ?", (semana.codigo, ticket_id))
        historial.registrar(conexion, entidad="muestra_auditoria", entidad_id=semana.codigo, accion="QUITAR",
                            usuario_id=sesion.usuario_id, valor_anterior=ticket_id)


def evaluaciones_pendientes(conexion: sqlite3.Connection, ahora: datetime | None = None) -> int:
    """Tickets de la muestra de la semana anterior sin evaluar (NOT-04)."""
    semana = periodos.semana_de(ahora or reloj.ahora()).anterior()
    fila = conexion.execute(
        "SELECT COUNT(*) FROM muestra_auditoria m WHERE m.semana = ? AND NOT EXISTS "
        "(SELECT 1 FROM evaluacion v WHERE v.ticket_id = m.ticket_id)", (semana.codigo,)).fetchone()
    if fila[0] == 0 and not conexion.execute("SELECT 1 FROM muestra_auditoria WHERE semana = ?", (semana.codigo,)).fetchone():
        return len(proponer_muestra(conexion, semana, ahora))
    return fila[0]


# --- CAL-05: histórico semana a semana ---

COLUMNAS_HISTORICO = ("Semana", "Atendidos", "Abiertos al corte", "Mediana resolución (h) ≈", "% SLA ≈",
                      "% documentación", "Atendidos vs. semana anterior", "Atendidos vs. promedio 4 semanas")


def historico_semanal(conexion: sqlite3.Connection, sesion: Sesion, tecnico_id: int, semanas: int = 8,
                      ahora: datetime | None = None) -> pd.DataFrame:
    """Series del técnico por semana ISO, con flechas y % de variación (CAL-05, CA-20)."""
    seguridad.tecnico_permitido(sesion, tecnico_id)
    calc = CalculadoraKPI(conexion, sesion, ahora)
    filtros = Filtros(tecnico_id=tecnico_id)
    lista = periodos.ultimos(periodos.semana_de(calc.ahora), semanas)
    filas = []
    for semana in lista:
        valor = lambda codigo: calc.calcular(codigo, semana, filtros, comparar=False).valor  # noqa: E731
        filas.append({
            "Semana": semana.codigo, "Atendidos": calc.contar_eventos(ev.SOLUCION, semana, filtros, distintos=True),
            "Abiertos al corte": valor("KPI-03"), "Mediana resolución (h) ≈": valor("KPI-06"),
            "% SLA ≈": valor("KPI-07"), "% documentación": valor("KPI-14"),
        })
    for i, fila in enumerate(filas):
        anterior = filas[i - 1]["Atendidos"] if i else None
        previas = [f["Atendidos"] for f in filas[max(0, i - 4):i]]
        promedio = statistics.fmean(previas) if len(previas) == 4 else None
        for columna, referencia in (("Atendidos vs. semana anterior", anterior),
                                    ("Atendidos vs. promedio 4 semanas", promedio)):
            flecha, porcentaje = _flecha(fila["Atendidos"], referencia)
            fila[columna] = flecha if porcentaje is None else f"{flecha} {abs(porcentaje):g} %"
    return pd.DataFrame(filas, columns=list(COLUMNAS_HISTORICO))


# --- CAL-06: rendimiento ---

def _grupo(fila) -> str:
    return fila["categoria_codigo"] or f"Prioridad {fila['prioridad_nivel']}"


def indices_velocidad(conexion: sqlite3.Connection, periodo: Periodo) -> dict[int, float]:
    """Índice normalizado por técnico = mediana de (horas del ticket / mediana del equipo en su categoría).

    Menos de 1 = más rápido que el equipo en casos equivalentes. Sin categoría asignada,
    el ticket se compara dentro de su prioridad.
    """
    filas = conexion.execute(
        "SELECT t.tecnico_principal_id, t.horas_resolucion, t.prioridad_nivel, c.categoria_codigo FROM ticket t "
        "LEFT JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi WHERE t.fecha_solucion >= ? AND t.fecha_solucion < ? "
        "AND t.horas_resolucion > 0 AND t.tecnico_principal_id IS NOT NULL",
        (_iso(periodo.inicio), _iso(periodo.fin)),
    ).fetchall()
    por_grupo: dict[str, list[float]] = {}
    for fila in filas:
        por_grupo.setdefault(_grupo(fila), []).append(fila["horas_resolucion"])
    medianas = {g: statistics.median(h) for g, h in por_grupo.items()}
    razones: dict[int, list[float]] = {}
    for fila in filas:
        mediana = medianas[_grupo(fila)]
        if mediana > 0:
            razones.setdefault(fila["tecnico_principal_id"], []).append(fila["horas_resolucion"] / mediana)
    return {tecnico: round(statistics.median(r), 3) for tecnico, r in razones.items()}


def rendimiento(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo,
                ahora: datetime | None = None) -> pd.DataFrame:
    """Por técnico: primera respuesta, solución y cierre (medianas), índice de velocidad,
    % de cierre formal, % de reaperturas y % de escalados."""
    calc = CalculadoraKPI(conexion, sesion, ahora)
    indices = indices_velocidad(conexion, periodo)
    filas = []
    for tecnico in responsables.tecnicos_visibles(conexion, sesion):
        filtros = Filtros(tecnico_id=tecnico["id"])
        valor = lambda codigo: calc.calcular(codigo, periodo, filtros, comparar=False).valor  # noqa: E731
        resueltos = calc.contar_eventos(ev.SOLUCION, periodo, filtros, distintos=True)
        cierres = calc.contar_eventos(ev.CIERRE, periodo, filtros, distintos=True)
        horas_cierre = [f[0] for f in conexion.execute(
            "SELECT horas_hasta_cierre FROM ticket WHERE tecnico_principal_id = ? AND fecha_cierre >= ? AND fecha_cierre < ?",
            (tecnico["id"], _iso(periodo.inicio), _iso(periodo.fin)))]
        filas.append({
            "Técnico": tecnico["nombre_mostrar"], "Turno": tecnico["turno"] or "—",
            "Primera respuesta (h)": valor("KPI-13"), "Solución (h) ≈": valor("KPI-06"),
            "Cierre (h) ≈": est.mediana(horas_cierre), "Índice de velocidad": indices.get(tecnico["id"]),
            "% cierre formal": est.porcentaje(min(cierres, resueltos), resueltos),
            "% reaperturas": valor("KPI-12"), "% escalamiento": valor("KPI-05"), "Resueltos": resueltos,
            "_id": tecnico["id"],
        })
    return pd.DataFrame(filas, columns=["Técnico", "Turno", "Primera respuesta (h)", "Solución (h) ≈", "Cierre (h) ≈",
                                        "Índice de velocidad", "% cierre formal", "% reaperturas", "% escalamiento",
                                        "Resueltos", "_id"])


def escalamiento_por_familia(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo) -> pd.DataFrame:
    """% de tickets escalados por técnico y familia, junto al del equipo (se compara solo por familia)."""
    visibles = {t["id"]: t["nombre_mostrar"] for t in responsables.tecnicos_visibles(conexion, sesion)}
    filas = conexion.execute(
        "SELECT t.tecnico_principal_id AS tecnico, substr(c.categoria_codigo, 1, 3) AS familia, "
        f"EXISTS (SELECT 1 FROM ticket_evento e WHERE e.ticket_id = t.id_glpi AND e.tipo = '{ev.ESCALAMIENTO}') AS escalado "
        "FROM ticket t JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
        "WHERE c.categoria_codigo IS NOT NULL AND t.fecha_apertura >= ? AND t.fecha_apertura < ?",
        (_iso(periodo.inicio), _iso(periodo.fin)),
    ).fetchall()
    datos = pd.DataFrame([dict(f) for f in filas], columns=["tecnico", "familia", "escalado"])
    if datos.empty:
        return pd.DataFrame(columns=["Familia", "Equipo %"])
    tabla = {"Equipo %": datos.groupby("familia")["escalado"].mean().mul(100).round(1)}
    for tecnico_id, nombre in visibles.items():
        propios = datos[datos["tecnico"] == tecnico_id]
        if not propios.empty:
            tabla[f"{nombre} %"] = propios.groupby("familia")["escalado"].mean().mul(100).round(1)
    return pd.DataFrame(tabla).reset_index().rename(columns={"familia": "Familia"})


# --- CAL-07: ranking (solo coordinador) ---

@dataclass
class FilaRanking:
    tecnico_id: int
    nombre: str
    turno: str | None
    atendidos: int
    velocidad: float | None
    calidad: float | None
    completitud: float | None
    indice: float | None
    evaluaciones: int = 0


@dataclass
class Ranking:
    filas: list[FilaRanking]
    excluidos: list[tuple[str, str]] = field(default_factory=list)  # (técnico, motivo)
    promedio: dict[str, float | None] = field(default_factory=dict)
    aviso: str = AVISO_RANKING


def _calidad_tecnico(conexion: sqlite3.Connection, tecnico_id: int, periodo: Periodo, penalizacion: float) -> tuple[float | None, int]:
    fila = conexion.execute(
        "SELECT AVG(v.porcentaje), SUM(v.criticos_fallidos), COUNT(*) FROM evaluacion v "
        "JOIN ticket t ON t.id_glpi = v.ticket_id WHERE v.vigente = 1 AND t.tecnico_principal_id = ? "
        "AND v.fecha >= ? AND v.fecha < ? AND v.porcentaje IS NOT NULL",
        (tecnico_id, _iso(periodo.inicio), _iso(periodo.fin)),
    ).fetchone()
    if not fila[2]:
        return None, 0
    return round(max(0.0, fila[0] - penalizacion * (fila[1] or 0)), 2), fila[2]


def ranking(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo, ahora: datetime | None = None) -> Ranking:
    """Tres dimensiones 0–100 e índice ponderado (CAL-07). Excluye a quien no llega a la
    muestra mínima o está marcado «no incluir en ranking» (CA-21)."""
    seguridad.exigir_coordinador(sesion)
    calc = CalculadoraKPI(conexion, sesion, ahora)
    minimo = parametros.entero(conexion, "muestra_minima")
    penalizacion = parametros.decimal_opcional(conexion, "penalizacion_critico") or 0
    pesos = {d: parametros.decimal_opcional(conexion, f"peso_ranking_{d}") or 0
             for d in ("calidad", "velocidad", "completitud")}
    indices = indices_velocidad(conexion, periodo)
    resultado = Ranking([])
    for tecnico in conexion.execute("SELECT * FROM tecnico WHERE activo = 1 ORDER BY nombre_mostrar"):
        filtros = Filtros(tecnico_id=tecnico["id"])
        atendidos = calc.contar_eventos(ev.SOLUCION, periodo, filtros, distintos=True)
        if not tecnico["incluir_en_ranking"]:
            resultado.excluidos.append((tecnico["nombre_mostrar"], "Marcado «no incluir en ranking»"))
            continue
        if atendidos < minimo:
            resultado.excluidos.append((tecnico["nombre_mostrar"], f"Muestra pequeña: {atendidos} tickets (mínimo {minimo})"))
            continue
        indice_velocidad = indices.get(tecnico["id"])
        velocidad = None if indice_velocidad is None else round(100 * min(1.0, max(0.0, 2 - indice_velocidad)), 2)
        calidad, evaluaciones = _calidad_tecnico(conexion, tecnico["id"], periodo, penalizacion)
        completitud = calc.calcular("KPI-09", periodo, filtros, comparar=False).valor
        dimensiones = {"calidad": calidad, "velocidad": velocidad, "completitud": completitud}
        disponibles = {d: v for d, v in dimensiones.items() if v is not None and pesos[d] > 0}
        indice = (round(sum(pesos[d] * v for d, v in disponibles.items()) / sum(pesos[d] for d in disponibles), 2)
                  if disponibles else None)
        resultado.filas.append(FilaRanking(tecnico["id"], tecnico["nombre_mostrar"], tecnico["turno"], atendidos,
                                           velocidad, calidad, completitud, indice, evaluaciones))
    resultado.filas.sort(key=lambda f: -1 if f.indice is None else f.indice, reverse=True)
    for dimension in ("velocidad", "calidad", "completitud", "indice"):
        valores = [getattr(f, dimension) for f in resultado.filas if getattr(f, dimension) is not None]
        resultado.promedio[dimension] = round(statistics.fmean(valores), 2) if valores else None
    return resultado


def tendencia_ranking(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo, meses: int = 3) -> pd.DataFrame:
    """Índice de cada técnico en los últimos `meses` meses que terminan en el período."""
    ultimo = periodos.mes_de(periodo.fin - timedelta(days=1))
    columnas = {}
    for mes in periodos.ultimos(ultimo, meses):
        columnas[mes.codigo] = {f.nombre: f.indice for f in ranking(conexion, sesion, mes).filas}
    return pd.DataFrame(columnas)


# --- CAL-08: incumplimiento por criterio ---

def incumplimiento_por_criterio(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo) -> pd.DataFrame:
    """% de «no cumple» por criterio en el período, del equipo y por técnico (propio, en consulta)."""
    visibles = {t["id"]: t["nombre_mostrar"] for t in responsables.tecnicos_visibles(conexion, sesion)}
    alerta = parametros.decimal_opcional(conexion, "alerta_criterio_porcentaje") or 30
    filas = conexion.execute(
        "SELECT d.criterio_id, c.descripcion, c.critico, d.resultado, t.tecnico_principal_id AS tecnico "
        "FROM evaluacion_detalle d JOIN evaluacion v ON v.id = d.evaluacion_id AND v.vigente = 1 "
        "JOIN criterio_calidad c ON c.id = d.criterio_id JOIN ticket t ON t.id_glpi = v.ticket_id "
        "WHERE d.resultado IN ('C', 'N') AND v.fecha >= ? AND v.fecha < ? ORDER BY c.rowid",
        (_iso(periodo.inicio), _iso(periodo.fin)),
    ).fetchall()
    datos = pd.DataFrame([dict(f) for f in filas], columns=["criterio_id", "descripcion", "critico", "resultado", "tecnico"])
    if datos.empty:
        return pd.DataFrame(columns=["Criterio", "Descripción", "Crítico", "Evaluados", "% incumplimiento equipo", "Capacitación"])
    datos["no"] = datos["resultado"] == "N"
    equipo = datos.groupby(["criterio_id", "descripcion", "critico"], sort=False).agg(
        Evaluados=("no", "size"), incumplimiento=("no", "mean")).reset_index()
    tabla = pd.DataFrame({
        "Criterio": equipo["criterio_id"], "Descripción": equipo["descripcion"],
        "Crítico": equipo["critico"].map({1: "CRÍTICO", 0: ""}), "Evaluados": equipo["Evaluados"],
        "% incumplimiento equipo": (equipo["incumplimiento"] * 100).round(1),
    })
    tabla["Capacitación"] = tabla["% incumplimiento equipo"].map(lambda p: "⚠ Tema de capacitación" if p >= alerta else "")
    for tecnico_id, nombre in visibles.items():
        propios = datos[datos["tecnico"] == tecnico_id]
        if not propios.empty:
            porcentaje = propios.groupby("criterio_id")["no"].mean().mul(100).round(1)
            tabla[f"{nombre} %"] = tabla["Criterio"].map(porcentaje)
    return tabla
