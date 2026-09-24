"""Paquete mensual gerencial (REP-10) y borradores de correo (spec 09, CA-14).

En la Fase 2 el paquete incluye: resumen ejecutivo (texto editable), REP-01,
REP-09, tendencias de 6 meses (snapshot), los 5 casos más repetidos, los
hallazgos del mes, SEGMOV y el plan de mejora. La calidad del área (KPI-14 y
KPI-15) se agrega en la Fase 3. Genera un PDF, un Excel y un borrador .eml con el
PDF adjunto, y registra el paquete para que NOT-03 deje de avisar.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from core import correo, parametros, reloj, seguridad
from core.analisis import hallazgos, snapshot
from core.analisis.hallazgos import SISTEMA
from core.analisis.kpis import CalculadoraKPI
from core.analisis.periodos import MES, Periodo
from core.errores import ErrorValidacion
from core.reportes import catalogo, graficos
from core.reportes.formatos import Hoja, Reporte, Tabla, escribir_excel, escribir_pdf
from core.seguridad import Sesion

TITULO = "REP-10 Paquete mensual gerencial"


@dataclass(frozen=True)
class Paquete:
    pdf: Path
    excel: Path
    correo: Path


def _hoja_texto(nombre: str, titulo: str, texto: str) -> Hoja:
    parrafos = [p.strip() for p in texto.splitlines() if p.strip()] or ["(sin texto)"]
    return Hoja(nombre, [Tabla(titulo, pd.DataFrame({titulo: parrafos}))])


def _hoja_tendencias(conexion: sqlite3.Connection) -> Hoja:
    calc = CalculadoraKPI(conexion, SISTEMA)
    criticos = [codigo for codigo, d in calc.definiciones.items() if d["critico"]]
    filas, imagenes = {}, []
    for codigo in criticos:
        puntos = snapshot.tendencia(conexion, codigo, cantidad=6)
        filas[f"{codigo} {calc.definiciones[codigo]['nombre']}"] = {p.periodo: p.valor for p in puntos}
        imagenes.append(graficos.a_png(graficos.tendencia(
            puntos, f"{codigo} {calc.definiciones[codigo]['nombre']} (6 meses)", calc.definiciones[codigo]["unidad"])))
    tabla = pd.DataFrame.from_dict(filas, orient="index").reset_index().rename(columns={"index": "KPI"})
    notas = ["Tendencias tomadas del snapshot mensual. Los meses sin snapshot no aparecen."]
    return Hoja("Tendencias", [Tabla("KPIs críticos en los últimos 6 meses", tabla)], imagenes, notas)


def _hoja_segmov(conexion: sqlite3.Connection, periodo: Periodo) -> Hoja:
    filas = conexion.execute(
        "SELECT e.nombre, e.cliente, s.casos, s.horas_asignadas, s.total_horas FROM segmov s "
        "JOIN estacion e ON e.id = s.estacion_id WHERE s.periodo = ? ORDER BY e.nombre", (periodo.codigo,),
    ).fetchall()
    if not filas:
        return Hoja("SEGMOV", [], [], ["SEGMOV del mes no generado: genere REP-08 con el total de horas y "
                                        "vuelva a generar el paquete."])
    tabla = pd.DataFrame([{"Estación": f["nombre"], "Cliente": f["cliente"] or "—", "Casos": f["casos"],
                           "Horas": f["horas_asignadas"]} for f in filas])
    return Hoja("SEGMOV", [Tabla(f"Distribución de {filas[0]['total_horas']:g} horas", tabla)],
                [graficos.a_png(graficos.barras(dict(zip(tabla["Estación"], tabla["Horas"])), "Horas por estación"))])


def generar(
    conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo, carpeta_exportaciones: Path,
    resumen_ejecutivo: str = "", plan_mejora: str = "", ahora: datetime | None = None,
) -> Paquete:
    """Genera el PDF, el Excel y el borrador .eml del paquete del mes. Solo el coordinador."""
    seguridad.exigir_coordinador(sesion)
    if periodo.granularidad != MES:
        raise ErrorValidacion("El paquete mensual se genera para un mes: elija un mes como período.")
    ahora = ahora or reloj.ahora()
    solicitud = catalogo.SolicitudReporte(conexion=conexion, sesion=sesion, periodo=periodo,
                                          carpeta_exportaciones=carpeta_exportaciones, ahora=ahora)
    rep01 = catalogo.CONSTRUCTORES["REP-01"](solicitud, ahora)
    rep09 = catalogo.CONSTRUCTORES["REP-09"](solicitud, ahora)
    rep05 = catalogo.CONSTRUCTORES["REP-05"](solicitud, ahora)
    rep05.hojas[0].tablas = rep05.hojas[0].tablas[:3]  # resumen, estados y 5 casos más repetidos
    hojas = [
        _hoja_texto("Resumen ejecutivo", "Resumen ejecutivo", resumen_ejecutivo),
        *rep01.hojas, *rep09.hojas, _hoja_tendencias(conexion), *rep05.hojas, _hoja_segmov(conexion, periodo),
        Hoja("Calidad del área", [], [], ["La calidad de documentación (KPI-14) y el índice general (KPI-15) "
                                          "se incorporan en la Fase 3."]),
        _hoja_texto("Plan de mejora", "Plan de mejora", plan_mejora),
    ]
    reporte = Reporte(TITULO, {**rep01.encabezado, "Filtros": "Sin filtros (paquete del área)"}, hojas)
    carpeta = carpeta_exportaciones / f"{ahora:%Y-%m}"
    base = f"REP-10_{periodo.codigo}_{ahora:%Y%m%d_%H%M%S}"
    pdf = escribir_pdf(reporte, carpeta / f"{base}.pdf")
    excel = escribir_excel(reporte, carpeta / f"{base}.xlsx")
    borrador = correo.crear_borrador(
        carpeta / f"{base}_correo.eml",
        asunto=f"Paquete mensual de soporte – {periodo.etiqueta}",
        cuerpo=(f"Buen día:\n\nAdjunto el paquete mensual de indicadores de soporte de {periodo.etiqueta} "
                "(indicadores, SLA, tendencias, hallazgos y SEGMOV).\n\n"
                + (f"Resumen:\n{resumen_ejecutivo.strip()}\n\n" if resumen_ejecutivo.strip() else "")
                + f"Saludos,\n{sesion.nombre}"),
        destinatarios=parametros.valor(conexion, "correo_jefatura") or "",
        adjuntos=[pdf],
    )
    with conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO paquete_mensual (periodo, generado_en, usuario_id, archivos_json) VALUES (?, ?, ?, ?)",
            (periodo.codigo, ahora.isoformat(sep=" "), sesion.usuario_id,
             json.dumps([pdf.name, excel.name, borrador.name], ensure_ascii=False)),
        )
    return Paquete(pdf, excel, borrador)


def borrador_hallazgos_altos(conexion: sqlite3.Connection, sesion: Sesion, carpeta_exportaciones: Path,
                             ahora: datetime | None = None) -> Path:
    """Borrador de correo con los hallazgos nuevos de severidad ALTA."""
    seguridad.exigir_coordinador(sesion)
    ahora = ahora or reloj.ahora()
    tabla = hallazgos.listar(conexion, sesion, estados=(hallazgos.NUEVO,), severidades=(hallazgos.ALTA,))
    if tabla.empty:
        raise ErrorValidacion("No hay hallazgos nuevos de severidad ALTA.")
    lineas = "\n".join(f"- {f['Regla']}: {f['Descripción']}" for _, f in tabla.iterrows())
    return correo.crear_borrador(
        carpeta_exportaciones / f"{ahora:%Y-%m}" / f"hallazgos_alta_{ahora:%Y%m%d_%H%M%S}.eml",
        asunto=f"Hallazgos de severidad alta – {ahora:%d/%m/%Y}",
        cuerpo=f"Buen día:\n\nHallazgos nuevos de severidad ALTA ({len(tabla)}):\n\n{lineas}\n\nSaludos,\n{sesion.nombre}",
        destinatarios=parametros.valor(conexion, "correo_jefatura") or "",
    )
