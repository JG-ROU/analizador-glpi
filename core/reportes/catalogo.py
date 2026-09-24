"""Catálogo de reportes (spec 09): REP-01 a REP-09 y REP-11 (REP-10 en paquete.py).

Formatos: PDF (fpdf2, con encabezado, filtros, fecha, usuario y paginación),
Excel (openpyxl, con tablas y gráficos como imagen) y CSV (la tabla principal).
Los reportes se guardan en exportaciones/AAAA-MM/ (mes de generación) con el
código, el período y la fecha y hora de generación en el nombre.
"""

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from core import parametros, reloj, seguridad
from core.analisis import distribucion, hallazgos, responsables, segmov, semaforo, series, sla, snapshot
from core.analisis import calidad_metricas as met
from core.analisis.calidad import NOMBRE_RESULTADO
from core.analisis import estadistica as est
from core.analisis.filtros import Filtros, filtros_permitidos
from core.analisis.kpis import NOMBRE_PRIORIDAD, CalculadoraKPI, ResultadoKPI, criticidad_global
from core.analisis.novedades import restriccion_tickets
from core.analisis.periodos import Periodo
from core.dominio import NOMBRE_TIPO_CASO
from core.errores import ErrorPermiso, ErrorValidacion
from core.reportes import graficos
from core.reportes.formatos import Hoja, Reporte, Tabla, anonimizar, escribir_csv, escribir_excel, escribir_pdf
from core.seguridad import Sesion

PDF = "PDF"
EXCEL = "EXCEL"
CSV = "CSV"
EXTENSIONES = {PDF: "pdf", EXCEL: "xlsx", CSV: "csv"}
COLUMNAS_PERSONALES = ("Autor", "Técnico")


@dataclass(frozen=True)
class DefinicionReporte:
    codigo: str
    nombre: str
    descripcion: str
    solo_coordinador: bool
    pide_horas: bool = False


REPORTES = (
    DefinicionReporte(
        "REP-01", "Resumen de indicadores",
        "KPIs visibles con valor, meta, semáforo y variación frente al período anterior; "
        "gráfico de brechas frente a la meta.",
        solo_coordinador=False,
    ),
    DefinicionReporte(
        "REP-02", "Estaciones",
        "Ranking por volumen, reincidencia y tiempo; familias por estación y casos repetidos.",
        solo_coordinador=False,
    ),
    DefinicionReporte(
        "REP-03", "Responsables – operativo",
        "Carga, atendidos, tiempos, SLA, resueltos sin cerrar y reaperturas por técnico. "
        "Un usuario de consulta obtiene solo sus propias métricas.",
        solo_coordinador=False,
    ),
    DefinicionReporte(
        "REP-04", "Tipificaciones",
        "Distribución por familia y categoría, tendencia por familia, categorías en crecimiento y OTR-01.",
        solo_coordinador=False,
    ),
    DefinicionReporte(
        "REP-05", "Hallazgos",
        "Hallazgos del período por regla y severidad, estado de revisión y casos repetidos.",
        solo_coordinador=False,
    ),
    DefinicionReporte(
        "REP-06", "Calidad de soporte – histórico",
        "Por técnico, semana a semana: atendidos, abiertos, tiempos, SLA y % de documentación, con "
        "subidas y bajadas frente a la semana anterior y al promedio de 4 semanas.",
        solo_coordinador=True,
    ),
    DefinicionReporte(
        "REP-07", "Calidad de soporte – comparativo",
        "Ranking CAL-07 (calidad, velocidad y completitud), radar frente al promedio del equipo, tendencia "
        "de 3 meses e incumplimiento por criterio (CAL-08). Uso interno: no publicar.",
        solo_coordinador=True,
    ),
    DefinicionReporte(
        "REP-08", "Distribución de horas SEGMOV",
        "Horas del mes repartidas entre las estaciones incluidas en SEGMOV según sus casos. "
        "Al generarlo se guarda la distribución del mes.",
        solo_coordinador=True, pide_horas=True,
    ),
    DefinicionReporte(
        "REP-09", "SLA",
        "Cumplimiento por prioridad, cliente, técnico y familia; tickets fuera de SLA o en riesgo; "
        "tendencia de 6 meses.",
        solo_coordinador=False,
    ),
    DefinicionReporte(
        "REP-11", "Datos para auditoría",
        "Tickets del período con campos derivados, clasificación, SLA y eventos, para revisión externa "
        "o el libro de control.",
        solo_coordinador=True,
    ),
)
REPORTES_POR_CODIGO = {r.codigo: r for r in REPORTES}


@dataclass
class SolicitudReporte:
    conexion: sqlite3.Connection
    sesion: Sesion
    periodo: Periodo
    carpeta_exportaciones: Path
    filtros: Filtros = field(default_factory=Filtros)
    ahora: datetime | None = None
    total_horas: float | None = None  # REP-08
    anonimizar: bool = False  # IMP-05, RNF-08


def disponibles(sesion: Sesion) -> list[DefinicionReporte]:
    return [r for r in REPORTES if sesion.es_coordinador or not r.solo_coordinador]


def generar(solicitud: SolicitudReporte, codigo: str, formato: str) -> Path:
    """Genera el reporte y devuelve la ruta del archivo creado."""
    definicion = REPORTES_POR_CODIGO.get(codigo)
    if definicion is None:
        raise ErrorValidacion(f"El reporte «{codigo}» no existe.")
    if formato not in EXTENSIONES:
        raise ErrorValidacion("Elija el formato PDF, Excel o CSV.")
    if definicion.solo_coordinador:
        seguridad.exigir_coordinador(solicitud.sesion)
    solicitud.filtros = filtros_permitidos(solicitud.sesion, solicitud.filtros)
    ahora = solicitud.ahora or reloj.ahora()
    reporte = CONSTRUCTORES[codigo](solicitud, ahora)
    if solicitud.anonimizar:
        for hoja in reporte.hojas:
            for tabla in hoja.tablas:
                tabla.datos = anonimizar(tabla.datos, COLUMNAS_PERSONALES)
    nombre = f"{codigo}_{solicitud.periodo.codigo}_{ahora:%Y%m%d_%H%M%S}.{EXTENSIONES[formato]}"
    ruta = solicitud.carpeta_exportaciones / f"{ahora:%Y-%m}" / nombre
    if formato == PDF:
        return escribir_pdf(reporte, ruta)
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
        partes.append("Tipo de caso: " + ", ".join(NOMBRE_TIPO_CASO[t] for t in filtros.tipos_caso))
    if filtros.estaciones:
        marcas = ", ".join("?" * len(filtros.estaciones))
        nombres = [f[0] for f in conexion.execute(f"SELECT nombre FROM estacion WHERE id IN ({marcas})",
                                                   filtros.estaciones)]
        partes.append("Estación: " + ", ".join(nombres))
    for etiqueta, valores in (("Cliente", filtros.clientes), ("Familia", filtros.familias),
                              ("Categoría", filtros.categorias), ("Causa", filtros.causas)):
        if valores:
            partes.append(f"{etiqueta}: " + ", ".join(valores))
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
            "% documentación": m.documentacion,
            "Muestra": est.AVISO_MUESTRA_PEQUENA if m.muestra_pequena else "",
        }
        for m in lista
    ], columns=[
        "Técnico", "Turno", "Abiertos al corte", "Abiertos por prioridad", "Atendidos",
        "Soluciones", "Escalamientos", "% escalamiento", "Mediana resolución (h)",
        "P90 resolución (h)", "% SLA", "Resueltos sin cerrar (informativo)", "Reaperturas",
        "Sin actualizar", "% documentación", "Muestra",
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


# --- REP-06 ---

def _rep06(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    tecnicos = responsables.tecnicos_visibles(solicitud.conexion, solicitud.sesion)
    if solicitud.filtros.tecnico_id is not None:
        tecnicos = [t for t in tecnicos if t["id"] == solicitud.filtros.tecnico_id]
    fin = min(ahora, solicitud.periodo.fin - timedelta(seconds=1))
    hojas = []
    for tecnico in tecnicos:
        tabla = met.historico_semanal(solicitud.conexion, solicitud.sesion, tecnico["id"], ahora=fin)
        series_graf = tabla.set_index("Semana")[["Atendidos", "% documentación"]].astype(float)
        hojas.append(Hoja(
            tecnico["nombre_mostrar"],
            [Tabla(f"{tecnico['nombre_mostrar']} · turno {tecnico['turno'] or 'sin asignar'}", tabla)],
            [graficos.a_png(graficos.lineas(series_graf, f"Semana a semana · {tecnico['nombre_mostrar']}"))],
        ))
    if not hojas:
        hojas.append(Hoja("Histórico", [Tabla("Histórico semanal", pd.DataFrame(columns=list(met.COLUMNAS_HISTORICO)))]))
    hojas[-1].notas += [
        "Cada técnico se compara primero consigo mismo: ↑ sube, ↓ baja, → igual frente a la semana "
        "anterior y al promedio de las 4 semanas previas.",
        "La carga varía por turno: no compare semanas de técnicos de turnos distintos.",
        "Tiempos aproximados (≈). " + est.AVISO_SIN_ESPERA + ".",
    ]
    return Reporte("REP-06 Calidad de soporte – histórico", _encabezado(solicitud, ahora), hojas)


# --- REP-07 ---

def tabla_ranking(resultado: met.Ranking) -> pd.DataFrame:
    return pd.DataFrame([{
        "Posición": posicion, "Técnico": f.nombre, "Turno": f.turno or "—", "Atendidos": f.atendidos,
        "Calidad": f.calidad, "Velocidad": f.velocidad, "Completitud": f.completitud, "Índice": f.indice,
        "Evaluaciones": f.evaluaciones,
    } for posicion, f in enumerate(resultado.filas, start=1)] + [{
        "Técnico": "Promedio del equipo", "Calidad": resultado.promedio.get("calidad"),
        "Velocidad": resultado.promedio.get("velocidad"), "Completitud": resultado.promedio.get("completitud"),
        "Índice": resultado.promedio.get("indice"),
    }], columns=["Posición", "Técnico", "Turno", "Atendidos", "Calidad", "Velocidad", "Completitud", "Índice",
                 "Evaluaciones"])


def _rep07(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    conexion, sesion, periodo = solicitud.conexion, solicitud.sesion, solicitud.periodo
    resultado = met.ranking(conexion, sesion, periodo, ahora)
    dimensiones = ["Calidad", "Velocidad", "Completitud"]
    promedio = [resultado.promedio.get(d) for d in ("calidad", "velocidad", "completitud")]
    radares = [graficos.a_png(graficos.radar(
        dimensiones, {f.nombre: [f.calidad, f.velocidad, f.completitud], "Promedio del equipo": promedio},
        f"{f.nombre} frente al equipo (0–100)")) for f in resultado.filas]
    tendencia = met.tendencia_ranking(conexion, sesion, periodo).reset_index().rename(columns={"index": "Técnico"})
    excluidos = pd.DataFrame(resultado.excluidos, columns=["Técnico", "Motivo"])
    incumplimiento = met.incumplimiento_por_criterio(conexion, sesion, periodo)
    notas = [
        resultado.aviso,
        "Ninguna métrica se usa sola: el índice combina calidad, velocidad (normalizada por categoría) y "
        "completitud según los pesos configurados.",
        "Se excluye a quien no alcanza la muestra mínima o está marcado «no incluir en ranking».",
    ]
    return Reporte("REP-07 Calidad de soporte – comparativo", _encabezado(solicitud, ahora), [
        Hoja("Ranking", [Tabla("Ranking del período", tabla_ranking(resultado)),
                         Tabla("Tendencia del índice (3 meses)", tendencia),
                         Tabla("Excluidos del ranking", excluidos)], radares, notas),
        Hoja("Incumplimiento", [Tabla("Incumplimiento por criterio (CAL-08)", incumplimiento)], [],
             ["⚠ marca los criterios con incumplimiento del equipo igual o superior al umbral: tema de capacitación."]),
    ])


# --- REP-02 ---

def _rep02(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    c, s, p, f = solicitud.conexion, solicitud.sesion, solicitud.periodo, solicitud.filtros
    ranking = distribucion.ranking_estaciones(c, s, p, f, ahora).drop(columns=["_id"])
    mapa = distribucion.mapa_calor(c, s, p, f)
    repetidos = []
    for nombre in ranking["Estación"]:
        if nombre != distribucion.SIN_ESTACION:
            tabla = distribucion.casos_repetidos_de_estacion(c, nombre)
            tabla.insert(0, "Estación", nombre)
            repetidos.append(tabla)
    casos = pd.concat(repetidos, ignore_index=True) if repetidos else pd.DataFrame(
        columns=["Estación", "Período", "Severidad", "Caso", "Veces", "Tendencia", "Tickets"])
    tablas = [Tabla("Ranking de estaciones", ranking)]
    if not mapa.empty:
        tablas.append(Tabla("Familias por estación", mapa.reset_index().rename(columns={"estacion": "Estación"})))
    tablas.append(Tabla("Casos repetidos abiertos (HAL-01)", casos))
    return Reporte("REP-02 Estaciones", _encabezado(solicitud, ahora), [Hoja(
        "Estaciones", tablas, [graficos.a_png(graficos.mapa_calor(mapa))],
        ["Según la estación asignada en la clasificación manual.", "Tiempos aproximados. " + est.AVISO_SIN_ESPERA + "."],
    )])


# --- REP-04 ---

def _rep04(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    c, s, p, f = solicitud.conexion, solicitud.sesion, solicitud.periodo, solicitud.filtros
    familias = distribucion.distribucion_familias(c, s, p, f)
    tendencia = distribucion.tendencia_familias(c, s, p, filtros=f)
    otros = CalculadoraKPI(c, s, ahora).calcular("KPI-10", p, f, comparar=False)
    tablas = [
        Tabla("Distribución por familia", pd.DataFrame(
            [{"Familia": k, "Tickets": v} for k, v in familias.items()], columns=["Familia", "Tickets"])),
        Tabla("Categorías", distribucion.distribucion_categorias(c, s, p, f)),
        Tabla("Categorías frente al promedio de 3 meses", distribucion.categorias_que_crecen(c, s, p, f)),
        Tabla("Tendencia mensual por familia", tendencia.reset_index().rename(columns={"index": "Mes"})),
    ]
    notas = [
        f"Uso de OTR-01 (KPI-10): {formatear_valor(otros, otros.valor)} · {semaforo.etiqueta(otros.semaforo)}",
        f"Tickets sin categoría asignada: {familias.get(distribucion.SIN_CATEGORIA, 0)}",
        "Según la categoría asignada en la clasificación manual.",
    ]
    imagenes = [graficos.a_png(graficos.barras(familias, "Tickets por familia")),
                graficos.a_png(graficos.lineas(tendencia, "Tendencia mensual por familia"))]
    return Reporte("REP-04 Tipificaciones", _encabezado(solicitud, ahora), [Hoja("Tipificaciones", tablas, imagenes, notas)])


# --- REP-05 ---

def _rep05(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    todos = hallazgos.listar(solicitud.conexion, solicitud.sesion, estados=())
    inicio, fin = f"{solicitud.periodo.inicio:%Y-%m-%d %H:%M}", f"{solicitud.periodo.fin:%Y-%m-%d %H:%M}"
    del_periodo = todos[(todos["Detectado"] < fin) & (todos["Actualizado"] >= inicio)]
    resumen = (del_periodo.groupby(["Regla", "Severidad"]).size().unstack(fill_value=0)
               .reindex(columns=[hallazgos.ALTA, hallazgos.MEDIA, hallazgos.BAJA], fill_value=0).reset_index())
    estados = del_periodo.groupby("Estado").size().reset_index(name="Hallazgos")
    repetidos = (del_periodo[del_periodo["Regla"].str.startswith("HAL-01")]
                 .assign(Veces=lambda t: t["Tickets"].str.count(",") + 1)
                 .sort_values("Veces", ascending=False).head(5))
    tablas = [
        Tabla("Hallazgos del período por regla y severidad", resumen),
        Tabla("Estado de revisión", estados),
        Tabla("Los 5 casos más repetidos", repetidos[["Entidad", "Período", "Veces", "Tickets"]]),
        Tabla("Detalle de hallazgos", del_periodo.drop(columns=["ID"])),
    ]
    return Reporte("REP-05 Hallazgos", _encabezado(solicitud, ahora), [Hoja("Hallazgos", tablas)])


# --- REP-08 ---

def _rep08(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    filas = segmov.guardar(solicitud.conexion, solicitud.sesion, solicitud.periodo, solicitud.total_horas)
    tabla = segmov.tabla(filas)
    grafico = graficos.barras({f.estacion: f.horas for f in filas}, "Horas asignadas por estación")
    notas = [
        f"Total de horas del mes: {solicitud.total_horas:g}. Casos del mes: {sum(f.casos for f in filas)}.",
        "horas = REDONDEAR(total × casos de la estación / casos totales; 1). La diferencia de redondeo "
        "se ajusta en la estación con mayor residuo para que la suma sea exacta.",
        "Solo entran las estaciones marcadas «Incluir en SEGMOV»; los casos son los tickets del mes con esa "
        "estación asignada.",
    ]
    return Reporte("REP-08 Distribución de horas SEGMOV", _encabezado(solicitud, ahora),
                   [Hoja("SEGMOV", [Tabla("Distribución de horas", tabla)], [graficos.a_png(grafico)], notas)])


# --- REP-09 ---

def detalle_sla(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo, filtros: Filtros,
                ahora: datetime) -> pd.DataFrame:
    """Tickets resueltos en el período y abiertos al corte, con su estado SLA."""
    restriccion, valores_restriccion = restriccion_tickets(conexion, sesion)
    condicion, valores = filtros.sql("t")
    corte = periodo.corte(ahora)
    objetivos = sla.objetivos(conexion)
    riesgo = parametros.decimal_opcional(conexion, "sla_riesgo_porcentaje") or 80
    filas = conexion.execute(
        "SELECT t.*, k.nombre_mostrar AS tecnico FROM ticket t LEFT JOIN tecnico k ON k.id = t.tecnico_principal_id "
        "WHERE ((t.fecha_solucion >= ? AND t.fecha_solucion < ?) OR (t.fecha_apertura < ? AND "
        "t.estado_codigo NOT IN ('RESUELTO', 'CERRADO')))" + condicion + restriccion + " ORDER BY t.fecha_apertura",
        [periodo.inicio.isoformat(sep=" "), periodo.fin.isoformat(sep=" "), corte.isoformat(sep=" "),
         *valores, *valores_restriccion],
    ).fetchall()
    registros = []
    for f in filas:
        solucion = datetime.fromisoformat(f["fecha_solucion"]) if f["fecha_solucion"] else None
        estado, horas = sla.estado(datetime.fromisoformat(f["fecha_apertura"]), solucion,
                                   objetivos.get(f["prioridad_nivel"]), corte, riesgo)
        registros.append({
            "ID": f["id_glpi"], "Título": f["titulo"], "Prioridad": f["prioridad"], "Técnico": f["tecnico"],
            "Apertura": f["fecha_apertura"][:16], "Solución ≈": (f["fecha_solucion"] or "")[:16],
            "Horas ≈": horas, "Objetivo (h)": objetivos.get(f["prioridad_nivel"]), "Estado SLA": sla.NOMBRES[estado],
        })
    return pd.DataFrame(registros, columns=["ID", "Título", "Prioridad", "Técnico", "Apertura", "Solución ≈",
                                            "Horas ≈", "Objetivo (h)", "Estado SLA"])


def _rep09(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    c, s, p, f = solicitud.conexion, solicitud.sesion, solicitud.periodo, solicitud.filtros
    calc = CalculadoraKPI(c, s, ahora)

    def cumplimiento(etiqueta: str, grupos: list[tuple[str, Filtros]]) -> Tabla:
        filas = []
        for nombre, filtros in grupos:
            r = calc.calcular("KPI-07", p, filtros, comparar=False)
            if r.denominador:
                filas.append({etiqueta: nombre, "Resueltos con objetivo": int(r.denominador),
                              "A tiempo": int(r.numerador), "% SLA": r.valor, "Semáforo": semaforo.etiqueta(r.semaforo)})
        return Tabla(f"Cumplimiento por {etiqueta.lower()}",
                     pd.DataFrame(filas, columns=[etiqueta, "Resueltos con objetivo", "A tiempo", "% SLA", "Semáforo"]),
                     columna_semaforo="Semáforo")

    def con(**cambios) -> Filtros:
        return replace(f, **cambios)

    global_ = calc.calcular("KPI-07", p, f, comparar=False)
    tablas = [
        cumplimiento("Prioridad", [(NOMBRE_PRIORIDAD[n], con(prioridades=(n,))) for n in sorted(NOMBRE_PRIORIDAD, reverse=True)]),
        cumplimiento("Cliente", [(cl, con(clientes=(cl,))) for (cl,) in
                                 c.execute("SELECT DISTINCT cliente FROM estacion WHERE cliente IS NOT NULL ORDER BY 1")]),
        cumplimiento("Familia", [(fa, con(familias=(fa,))) for (fa,) in
                                 c.execute("SELECT DISTINCT familia FROM categoria ORDER BY 1")]),
    ]
    try:
        tecnicos = responsables.tecnicos_visibles(c, s)
        tablas.append(cumplimiento("Técnico", [(t["nombre_mostrar"], con(tecnico_id=t["id"])) for t in tecnicos]))
    except ErrorPermiso:
        pass  # jefatura: sin detalle por técnico
    try:
        detalle = detalle_sla(c, s, p, f, ahora)
        fuera = detalle[detalle["Estado SLA"].isin([sla.NOMBRES[sla.INCUMPLIDO], sla.NOMBRES[sla.EN_RIESGO]])]
        tablas.insert(0, Tabla("Tickets fuera de SLA o en riesgo", fuera))
    except ErrorPermiso:
        pass
    puntos = snapshot.tendencia(c, "KPI-07", cantidad=6)
    notas = [
        f"Cumplimiento global del período: {formatear_valor(global_, global_.valor)} · {semaforo.etiqueta(global_.semaforo)}",
        "Objetivo por prioridad según los parámetros sla_horas_*; sin fecha de vencimiento en la exportación.",
        "Tiempos aproximados. " + est.AVISO_SIN_ESPERA + ".",
    ]
    if all(v is None for v in sla.objetivos(c).values()):
        notas.insert(0, "No hay objetivos de SLA definidos: configúrelos en Configuración > Parámetros.")
    return Reporte("REP-09 SLA", _encabezado(solicitud, ahora), [Hoja(
        "SLA", tablas, [graficos.a_png(graficos.tendencia(puntos, "Tendencia de cumplimiento SLA (6 meses)", "%"))],
        notas)])


# --- REP-11 ---

def _rep11(solicitud: SolicitudReporte, ahora: datetime) -> Reporte:
    c, p = solicitud.conexion, solicitud.periodo
    condicion, valores = solicitud.filtros.sql("t")
    objetivos = sla.objetivos(c)
    filas = c.execute(
        "SELECT t.*, k.nombre_mostrar AS tecnico, e.nombre AS estacion, e.cliente, cl.categoria_codigo, "
        "cl.causa_codigo, cl.tipo_solucion_codigo, "
        "(SELECT COUNT(*) FROM ticket_evento v WHERE v.ticket_id = t.id_glpi AND v.tipo = 'ESCALAMIENTO') AS escalamientos, "
        "(SELECT COUNT(*) FROM ticket_evento v WHERE v.ticket_id = t.id_glpi AND v.tipo = 'REAPERTURA') AS reaperturas, "
        "ev.porcentaje AS eval_porcentaje, ev.resultado AS eval_resultado, ev.criticos_fallidos AS eval_criticos, "
        "ev.fecha AS eval_fecha, ev.version AS eval_version, ev.retroalimentacion AS eval_retro "
        "FROM ticket t LEFT JOIN tecnico k ON k.id = t.tecnico_principal_id "
        "LEFT JOIN evaluacion ev ON ev.ticket_id = t.id_glpi AND ev.vigente = 1 "
        "LEFT JOIN ticket_clasificacion cl ON cl.ticket_id = t.id_glpi LEFT JOIN estacion e ON e.id = cl.estacion_id "
        "WHERE t.fecha_apertura >= ? AND t.fecha_apertura < ?" + condicion + " ORDER BY t.id_glpi",
        [p.inicio.isoformat(sep=" "), p.fin.isoformat(sep=" "), *valores],
    ).fetchall()
    registros = []
    for f in filas:
        solucion = datetime.fromisoformat(f["fecha_solucion"]) if f["fecha_solucion"] else None
        estado_sla, _ = sla.estado(datetime.fromisoformat(f["fecha_apertura"]), solucion,
                                   objetivos.get(f["prioridad_nivel"]), p.corte(ahora), 80)
        registros.append({
            "ID": f["id_glpi"], "Título": f["titulo"], "Estado": f["estado"], "Prioridad": f["prioridad"],
            "P1": "Sí" if f["es_p1"] else "No", "Técnico": f["tecnico"], "Autor": f["autor"],
            "Apertura": f["fecha_apertura"][:16], "Turno": f["turno_apertura"],
            "Última actualización": f["ultima_actualizacion"][:16],
            "Solución ≈": (f["fecha_solucion"] or "")[:16], "Cierre ≈": (f["fecha_cierre"] or "")[:16],
            "Horas resolución ≈": f["horas_resolucion"], "Horas hasta cierre ≈": f["horas_hasta_cierre"],
            "Tipo de caso": NOMBRE_TIPO_CASO[f["tipo_caso"]], "Escalamientos": f["escalamientos"],
            "Reaperturas": f["reaperturas"], "Estación": f["estacion"], "Cliente": f["cliente"],
            "Categoría": f["categoria_codigo"], "Causa": f["causa_codigo"],
            "Tipo de solución": f["tipo_solucion_codigo"], "Estado SLA": sla.NOMBRES[estado_sla],
            "Evaluación %": f["eval_porcentaje"],
            "Resultado evaluación": NOMBRE_RESULTADO.get(f["eval_resultado"], "") if f["eval_resultado"] else "",
            "Críticos fallidos": f["eval_criticos"], "Fecha evaluación": (f["eval_fecha"] or "")[:16],
            "Versión evaluación": f["eval_version"], "Retroalimentación": f["eval_retro"],
            "Entidad (GLPI)": f["entidad"], "Ubicación (GLPI)": f["ubicacion"],
        })
    datos = pd.DataFrame(registros)
    notas = ["Fechas de solución y cierre aproximadas (detectadas entre importaciones). "
             "La evaluación de calidad es la versión vigente de cada ticket (vacía si no se evaluó)."]
    return Reporte("REP-11 Datos para auditoría", _encabezado(solicitud, ahora),
                   [Hoja("Auditoría", [Tabla("Tickets del período", datos)], [], notas)])


CONSTRUCTORES = {
    "REP-01": _rep01, "REP-02": _rep02, "REP-03": _rep03, "REP-04": _rep04,
    "REP-05": _rep05, "REP-06": _rep06, "REP-07": _rep07, "REP-08": _rep08, "REP-09": _rep09, "REP-11": _rep11,
}
