"""Catálogo de reportes de la Fase 1: REP-01 y REP-03 en Excel y CSV (spec 09).

Los reportes se guardan en exportaciones/AAAA-MM/ (mes de generación) con el
código, el período y la fecha y hora de generación en el nombre.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from core import reloj
from core.analisis import estadistica as est
from core.analisis import responsables, semaforo, series
from core.analisis.filtros import Filtros, filtros_permitidos
from core.analisis.kpis import NOMBRE_PRIORIDAD, CalculadoraKPI, ResultadoKPI, criticidad_global
from core.analisis.periodos import Periodo
from core.errores import ErrorValidacion
from core.reportes import graficos
from core.reportes.formatos import Hoja, Reporte, Tabla, escribir_csv, escribir_excel
from core.seguridad import Sesion

EXCEL = "EXCEL"
CSV = "CSV"
EXTENSIONES = {EXCEL: "xlsx", CSV: "csv"}


@dataclass(frozen=True)
class DefinicionReporte:
    codigo: str
    nombre: str
    descripcion: str
    solo_coordinador: bool


REPORTES = (
    DefinicionReporte(
        "REP-01", "Resumen de indicadores",
        "KPIs visibles con valor, meta, semáforo y variación frente al período anterior; "
        "gráfico de brechas frente a la meta.",
        solo_coordinador=False,
    ),
    DefinicionReporte(
        "REP-03", "Responsables – operativo",
        "Carga, atendidos, tiempos, SLA, resueltos sin cerrar y reaperturas por técnico. "
        "Un usuario de consulta obtiene solo sus propias métricas.",
        solo_coordinador=False,
    ),
)
REPORTES_POR_CODIGO = {r.codigo: r for r in REPORTES}


@dataclass
class SolicitudReporte:
    conexion: sqlite3.Connection
    sesion: Sesion
    periodo: Periodo
    carpeta_exportaciones: Path
    filtros: Filtros = Filtros()
    ahora: datetime | None = None


def generar(solicitud: SolicitudReporte, codigo: str, formato: str) -> Path:
    """Genera el reporte y devuelve la ruta del archivo creado."""
    if codigo not in REPORTES_POR_CODIGO:
        raise ErrorValidacion(f"El reporte «{codigo}» no existe.")
    if formato not in EXTENSIONES:
        raise ErrorValidacion("Elija el formato Excel o CSV.")
    solicitud.filtros = filtros_permitidos(solicitud.sesion, solicitud.filtros)
    ahora = solicitud.ahora or reloj.ahora()
    reporte = {"REP-01": _rep01, "REP-03": _rep03}[codigo](solicitud, ahora)
    nombre = (
        f"{codigo}_{solicitud.periodo.codigo}_{ahora:%Y%m%d_%H%M%S}.{EXTENSIONES[formato]}"
    )
    ruta = solicitud.carpeta_exportaciones / f"{ahora:%Y-%m}" / nombre
    if formato == EXCEL:
        return escribir_excel(reporte, ruta)
    return escribir_csv(reporte.hojas[0].tablas[0], ruta)


# --- Apoyo ---

def describir_filtros(conexion: sqlite3.Connection, filtros: Filtros) -> str:
    partes = []
    if filtros.tecnico_id is not None:
        fila = conexion.execute(
            "SELECT nombre_mostrar FROM tecnico WHERE id = ?", (filtros.tecnico_id,)
        ).fetchone()
        partes.append(f"Técnico: {fila[0] if fila else filtros.tecnico_id}")
    if filtros.turno:
        partes.append(f"Turno: {filtros.turno}")
    if filtros.prioridades:
        partes.append("Prioridad: " + ", ".join(NOMBRE_PRIORIDAD[n] for n in filtros.prioridades))
    if filtros.estados:
        partes.append("Estado: " + ", ".join(series.NOMBRE_ESTADO[e] for e in filtros.estados))
    if filtros.tipos_caso:
        partes.append("Tipo de caso: " + ", ".join(filtros.tipos_caso))
    return "; ".join(partes) or "Sin filtros"


def _encabezado(solicitud: SolicitudReporte, ahora: datetime) -> dict[str, str]:
    return {
        "Período": solicitud.periodo.etiqueta,
        "Filtros": describir_filtros(solicitud.conexion, solicitud.filtros),
        "Generado": f"{ahora:%d/%m/%Y %H:%M}",
        "Usuario": solicitud.sesion.nombre,
    }


def formatear_valor(resultado: ResultadoKPI, valor: float | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:g}"
    return f"{texto} %" if resultado.unidad == "%" else f"{texto} {resultado.unidad}"


def texto_variacion(resultado: ResultadoKPI) -> str:
    puntos = resultado.variacion_puntos
    if puntos is None:
        return "—"
    flecha = "▲" if puntos > 0 else "▼" if puntos < 0 else "="
    if resultado.unidad == "%":
        return f"{flecha} {abs(puntos):g} puntos"
    porcentual = resultado.variacion_porcentual
    return f"{flecha} {abs(porcentual):g} %" if porcentual is not None else f"{flecha} {abs(puntos):g}"


# --- REP-01 ---

def _rep01(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    calc = CalculadoraKPI(solicitud.conexion, solicitud.sesion, ahora)
    resultados = calc.calcular_visibles(solicitud.periodo, solicitud.filtros)
    indicadores = pd.DataFrame([
        {
            "Código": r.codigo,
            "Indicador": r.nombre,
            "Valor": formatear_valor(r, r.valor),
            "Meta": formatear_valor(r, r.meta) if r.meta is not None else "—",
            "Semáforo": semaforo.etiqueta(r.semaforo),
            "Período anterior": formatear_valor(r, r.valor_anterior),
            "Variación": texto_variacion(r),
            "Base de cálculo": r.cantidad,
            "Observaciones": "; ".join(
                ([est.AVISO_MUESTRA_PEQUENA] if r.muestra_pequena else []) + [n for n in r.notas if n]
            ),
        }
        for r in resultados
    ])
    tablas = [Tabla("Indicadores", indicadores, columna_semaforo="Semáforo")]
    tiempos = next((r for r in resultados if r.codigo == "KPI-06"), None)
    if tiempos and tiempos.detalle:
        tablas.append(Tabla(
            "Tiempo de resolución por prioridad (horas, aproximado)",
            pd.DataFrame([
                {
                    "Prioridad": x["prioridad"], "Tickets": x["tickets"], "Mediana": x["mediana"],
                    "P90": x["p90"], "Promedio": x["promedio"],
                    "Semáforo": semaforo.etiqueta(x["semaforo"]),
                    "Muestra": est.AVISO_MUESTRA_PEQUENA if x["muestra_pequena"] else "",
                }
                for x in tiempos.detalle
            ]),
            columna_semaforo="Semáforo",
        ))
    criticidad = semaforo.etiqueta(criticidad_global(resultados))
    imagenes = [
        graficos.a_png(graficos.brecha_vs_meta(series.brechas(resultados, calc.definiciones))),
        graficos.a_png(graficos.recibidos_resueltos(
            series.recibidos_resueltos(calc, solicitud.periodo, solicitud.filtros)
        )),
    ]
    notas = [
        f"Criticidad global del período: {criticidad}",
        "Gestiones (KPI-04, KPI-05): se cuentan eventos de solución y de escalamiento del "
        "período; un ticket escalado dos veces cuenta dos.",
        est.AVISO_SIN_ESPERA + ".",
    ]
    return Reporte(
        "REP-01 Resumen de indicadores",
        _encabezado(solicitud, ahora),
        [Hoja("Resumen", tablas, imagenes, notas)],
    )


# --- REP-03 ---

def _rep03(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    lista = responsables.metricas(
        solicitud.conexion, solicitud.sesion, solicitud.periodo, solicitud.filtros.tecnico_id, ahora
    )
    datos = pd.DataFrame([
        {
            "Técnico": m.nombre,
            "Turno": m.turno or "—",
            "Abiertos al corte": m.abiertos,
            "Abiertos por prioridad": ", ".join(f"{k}: {v}" for k, v in m.abiertos_por_prioridad.items()) or "—",
            "Atendidos": m.atendidos,
            "Soluciones": m.soluciones,
            "Escalamientos": m.escalamientos,
            "% escalamiento": m.tasa_escalamiento,
            "Mediana resolución (h)": m.mediana_resolucion,
            "P90 resolución (h)": m.p90_resolucion,
            "% SLA": m.sla,
            "Resueltos sin cerrar (informativo)": m.sin_cerrar_cantidad,
            "Reaperturas": m.reaperturas,
            "Sin actualizar": m.sin_actualizar,
            "Muestra": est.AVISO_MUESTRA_PEQUENA if m.muestra_pequena else "",
        }
        for m in lista
    ], columns=[
        "Técnico", "Turno", "Abiertos al corte", "Abiertos por prioridad", "Atendidos",
        "Soluciones", "Escalamientos", "% escalamiento", "Mediana resolución (h)",
        "P90 resolución (h)", "% SLA", "Resueltos sin cerrar (informativo)", "Reaperturas",
        "Sin actualizar", "Muestra",
    ])
    carga = {m.nombre: m.abiertos_por_prioridad for m in lista if m.abiertos_por_prioridad}
    notas = [
        "El número de tickets es informativo (carga), no una calificación del técnico.",
        "Resueltos sin cerrar: el cierre depende del visto bueno del autor; es informativo.",
        "Tiempos aproximados: la fecha de solución es la última actualización del ticket "
        "en la importación en que apareció resuelto. " + est.AVISO_SIN_ESPERA + ".",
    ]
    return Reporte(
        "REP-03 Responsables – operativo",
        _encabezado(solicitud, ahora),
        [Hoja("Responsables", [Tabla("Métricas por técnico", datos)],
              [graficos.a_png(graficos.carga_por_tecnico(carga))], notas)],
    )
