"""Paquete mensual gerencial (REP-10), resúmenes semanales por técnico y borradores
de correo (spec 09, CA-14).

El paquete incluye: resumen ejecutivo (texto editable), REP-01, REP-09, tendencias
de 6 meses (snapshot), los 5 casos más repetidos, los hallazgos del mes, la calidad
del área (KPI-14 y KPI-15, sin datos por técnico), SEGMOV y el plan de mejora.
Genera un PDF, un Excel y un borrador .eml con el PDF adjunto, y registra el
paquete para que NOT-03 deje de avisar.

El resumen semanal de cada técnico lleva solo sus propias métricas y la
retroalimentación de sus evaluaciones; nunca el ranking ni datos de otros.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from core import correo, parametros, reloj, seguridad
from core.analisis import calidad, hallazgos, periodos, responsables, snapshot
from core.analisis import calidad_metricas as met
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


def _hoja_calidad(conexion: sqlite3.Connection, periodo: Periodo) -> Hoja:
    """Calidad del área: KPI-14 y KPI-15 del mes con su tendencia, resultados de las
    evaluaciones y criterios con más incumplimiento. Sin datos por técnico."""
    calc = CalculadoraKPI(conexion, SISTEMA)
    filas, imagenes = [], []
    for codigo in ("KPI-14", "KPI-15"):
        if codigo not in calc.definiciones:
            continue
        definicion = calc.definiciones[codigo]
        resultado = calc.calcular(codigo, periodo)
        filas.append({
            "KPI": f"{codigo} {definicion['nombre']}",
            "Valor": catalogo.formatear_valor(resultado, resultado.valor),
            "Meta": catalogo.formatear_valor(resultado, resultado.meta) if resultado.meta is not None else "—",
            "Variación": catalogo.texto_variacion(resultado),
        })
        puntos = snapshot.tendencia(conexion, codigo, cantidad=6)
        if puntos:
            imagenes.append(graficos.a_png(graficos.tendencia(
                puntos, f"{codigo} {definicion['nombre']} (6 meses)", definicion["unidad"])))
    tablas = [Tabla("Indicadores de calidad del área", pd.DataFrame(filas, columns=["KPI", "Valor", "Meta", "Variación"]))]
    conteo = conexion.execute(
        "SELECT resultado, COUNT(*) AS n, AVG(porcentaje) AS promedio FROM evaluacion "
        "WHERE vigente = 1 AND fecha >= ? AND fecha < ? GROUP BY resultado",
        (f"{periodo.inicio:%Y-%m-%d %H:%M:%S}", f"{periodo.fin:%Y-%m-%d %H:%M:%S}"),
    ).fetchall()
    tablas.append(Tabla("Evaluaciones de calidad del mes", pd.DataFrame(
        [{"Resultado": calidad.NOMBRE_RESULTADO.get(f["resultado"], f["resultado"]), "Evaluaciones": f["n"],
          "Puntaje promedio %": None if f["promedio"] is None else round(f["promedio"], 1)} for f in conteo],
        columns=["Resultado", "Evaluaciones", "Puntaje promedio %"])))
    incumplimiento = met.incumplimiento_por_criterio(conexion, SISTEMA, periodo)
    columnas = ["Criterio", "Descripción", "Crítico", "Evaluados", "% incumplimiento equipo", "Capacitación"]
    tablas.append(Tabla("Criterios con más incumplimiento", incumplimiento[columnas]
                        .sort_values("% incumplimiento equipo", ascending=False).head(5)))
    notas = ["Datos del área en conjunto; el detalle por técnico y el ranking son de uso interno del coordinador."]
    if not conteo:
        notas.append("No hay evaluaciones de calidad registradas en el mes.")
    return Hoja("Calidad del área", tablas, imagenes, notas)


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
        _hoja_calidad(conexion, periodo),
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
                "(indicadores, SLA, tendencias, hallazgos, calidad del área y SEGMOV).\n\n"
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


# --- Resumen semanal por técnico (spec 09) ---

def semana_resumen(ahora: datetime) -> Periodo:
    """La última semana ISO completa antes de `ahora`."""
    return periodos.semana_de(periodos.semana_de(ahora).inicio - timedelta(days=1))


def _numero(valor: float | None, sufijo: str = "") -> str:
    return "sin dato" if valor is None else f"{round(valor, 1):g}{sufijo}"


def cuerpo_resumen_semanal(conexion: sqlite3.Connection, sesion: Sesion, tecnico_id: int, semana: Periodo,
                           ahora: datetime | None = None) -> tuple[str, bool]:
    """Texto del resumen de un técnico (solo sus métricas y su retroalimentación) y si
    tuvo actividad en la semana (atendidos o evaluaciones)."""
    ahora = ahora or reloj.ahora()
    m = responsables.metricas(conexion, sesion, semana, tecnico_id, ahora)[0]
    lineas = [
        f"Hola, {m.nombre}:", "",
        f"Este es tu resumen de la semana {semana.etiqueta}. Es para conversar y mejorar, no una calificación.", "",
        "Tus métricas de la semana:",
        f"- Tickets atendidos (resueltos): {m.atendidos}",
        f"- Soluciones: {m.soluciones} · Escalamientos: {m.escalamientos}",
        f"- Abiertos a tu nombre al corte: {m.abiertos}",
        f"- Mediana de resolución (aprox.): {_numero(m.mediana_resolucion, ' h')}",
        f"- Cumplimiento de SLA (aprox.): {_numero(m.sla, ' %')}",
        f"- Documentación (KPI-14): {_numero(m.documentacion, ' %')}",
        f"- Reaperturas: {m.reaperturas} · Sin actualizar: {m.sin_actualizar}",
    ]
    historico = met.historico_semanal(conexion, sesion, tecnico_id, semanas=5,
                                      ahora=min(ahora, semana.fin - timedelta(seconds=1)))
    if not historico.empty:
        ultima = historico.iloc[-1]
        lineas += ["", "Frente a ti mismo:",
                   f"- Atendidos frente a la semana anterior: {ultima['Atendidos vs. semana anterior']}",
                   f"- Atendidos frente al promedio de 4 semanas: {ultima['Atendidos vs. promedio 4 semanas']}"]
    evaluaciones = conexion.execute(
        "SELECT v.ticket_id, v.porcentaje, v.resultado, v.retroalimentacion FROM evaluacion v "
        "JOIN ticket t ON t.id_glpi = v.ticket_id WHERE v.vigente = 1 AND t.tecnico_principal_id = ? "
        "AND v.fecha >= ? AND v.fecha < ? ORDER BY v.fecha",
        (tecnico_id, f"{semana.inicio:%Y-%m-%d %H:%M:%S}", f"{semana.fin:%Y-%m-%d %H:%M:%S}"),
    ).fetchall()
    lineas += ["", "Evaluaciones de calidad de tus tickets en la semana:"]
    for e in evaluaciones:
        puntaje = "sin puntaje" if e["porcentaje"] is None else f"{e['porcentaje']:g} %"
        lineas.append(f"- Ticket {e['ticket_id']}: {puntaje} "
                      f"({calidad.NOMBRE_RESULTADO.get(e['resultado'], e['resultado'])})")
        if (e["retroalimentacion"] or "").strip():
            lineas.append(f"  Retroalimentación: {e['retroalimentacion'].strip()}")
    if not evaluaciones:
        lineas.append("- No se evaluaron tickets tuyos esta semana.")
    lineas += ["", "Si quieres revisar algún caso, conversemos.", "", "Saludos,", sesion.nombre]
    return "\n".join(lineas), bool(m.atendidos or evaluaciones)


def resumenes_semanales(conexion: sqlite3.Connection, sesion: Sesion, carpeta_exportaciones: Path,
                        semana: Periodo | None = None, ahora: datetime | None = None) -> list[Path]:
    """Un borrador .eml por técnico activo con atendidos o evaluaciones en la semana. Solo el coordinador.

    El destinatario queda vacío: la aplicación no guarda correos de técnicos y se
    completa en Outlook antes de enviar.
    """
    seguridad.exigir_coordinador(sesion)
    ahora = ahora or reloj.ahora()
    semana = semana or semana_resumen(ahora)
    carpeta = carpeta_exportaciones / f"{ahora:%Y-%m}" / f"resumenes_{semana.codigo}_{ahora:%Y%m%d_%H%M%S}"
    rutas = []
    tecnicos = conexion.execute("SELECT id, nombre_mostrar FROM tecnico WHERE activo = 1 ORDER BY nombre_mostrar")
    for tecnico in tecnicos.fetchall():
        cuerpo, con_actividad = cuerpo_resumen_semanal(conexion, sesion, tecnico["id"], semana, ahora)
        if not con_actividad:
            continue
        nombre_archivo = "".join(c if c.isalnum() else "_" for c in tecnico["nombre_mostrar"])
        rutas.append(correo.crear_borrador(
            carpeta / f"resumen_{nombre_archivo}.eml",
            asunto=f"Tu resumen semanal de soporte – {semana.etiqueta}",
            cuerpo=cuerpo,
        ))
    if not rutas:
        raise ErrorValidacion(f"Ningún técnico tuvo tickets atendidos ni evaluaciones en la semana {semana.etiqueta}.")
    return rutas
