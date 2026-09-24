"""Datos iniciales: parámetros, KPIs predefinidos y catálogos (spec 04, 05 y 08).

Se insertan solo si no existen, así que nunca sobrescriben lo que el usuario editó.
Los valores que la especificación no fija (objetivos de SLA, umbrales de KPI-06)
quedan vacíos: los define el coordinador en el asistente o en Configuración.
Los catálogos de categorías, causas y tipos de solución se leen de spec/catalogos/.
"""

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from core import rutas
from core.dominio import PRIORIDADES
from core.errores import ErrorAplicacion

CARPETA_CATALOGOS = Path("spec") / "catalogos"

# Umbrales iniciales de "sin actualizar" por nivel de prioridad (spec 05, KPI-16)
_HORAS_SIN_ACTUALIZAR = {6: 1, 5: 4, 4: 4, 3: 24, 2: 24, 1: 24}


@dataclass(frozen=True)
class ParametroInicial:
    clave: str
    valor: str | None
    tipo: str
    grupo: str
    descripcion: str
    minimo: float | None = None
    maximo: float | None = None


@dataclass(frozen=True)
class KpiInicial:
    codigo: str
    nombre: str
    descripcion: str
    tipo_calculo: str
    unidad: str
    direccion: str
    umbral_verde: float | None = None
    umbral_amarillo: float | None = None
    meta: float | None = None
    aproximado: bool = False
    critico: bool = False


def _parametros() -> list[ParametroInicial]:
    parametros = [
        ParametroInicial(
            "muestra_minima", "10", "ENTERO", "Cálculo",
            "Tickets mínimos para mostrar un indicador sin el aviso "
            "«muestra pequeña» y para entrar en rankings (RN-04).",
            minimo=1,
        ),
        ParametroInicial(
            "prioridad_p1", "6", "ENTERO", "Prioridades",
            "Nivel de prioridad desde el cual un ticket es P1 "
            "(6 = Mayor, 5 = Muy urgente, 4 = Urgente).",
            minimo=1, maximo=6,
        ),
        ParametroInicial(
            "dias_resuelto_sin_cerrar", "2", "ENTERO", "Alertas",
            "Días en estado Resuelto a partir de los cuales el ticket cuenta "
            "como resuelto sin cerrar.",
            minimo=0,
        ),
        ParametroInicial(
            "dias_importacion_desactualizada", "1", "ENTERO", "Alertas",
            "Días sin importar a partir de los cuales se avisa que los datos "
            "están desactualizados.",
            minimo=1,
        ),
        ParametroInicial(
            "dias_escalado_alerta", "5", "ENTERO", "Alertas",
            "Días en estado Escalado para el acceso rápido «escalados antiguos» "
            "de Novedades.",
            minimo=1,
        ),
    ]
    for prioridad in PRIORIDADES:
        parametros.append(
            ParametroInicial(
                f"sla_horas_{prioridad.clave}", None, "DECIMAL", "SLA",
                f"Objetivo de resolución en horas para prioridad {prioridad.nombre} "
                "(KPI-07).",
                minimo=0,
            )
        )
    for prioridad in PRIORIDADES:
        parametros.append(
            ParametroInicial(
                f"horas_sin_actualizar_{prioridad.clave}",
                str(_HORAS_SIN_ACTUALIZAR[prioridad.nivel]), "DECIMAL", "Sin actualizar",
                f"Horas sin actualización a partir de las cuales un ticket abierto de "
                f"prioridad {prioridad.nombre} cuenta como sin actualizar (KPI-16).",
                minimo=0,
            )
        )
    parametros += _parametros_fase2()
    for prioridad in PRIORIDADES:
        for color in ("verde", "amarillo"):
            parametros.append(
                ParametroInicial(
                    f"kpi06_{color}_horas_{prioridad.clave}", None, "DECIMAL",
                    "Semáforo de tiempo de resolución",
                    f"Umbral {color} en horas de la mediana de resolución para "
                    f"prioridad {prioridad.nombre} (KPI-06). Vacío = informativo.",
                    minimo=0,
                )
            )
    return parametros


def _parametros_fase2() -> list[ParametroInicial]:
    """Umbrales de hallazgos (spec 08) y de SLA en riesgo (spec 09)."""
    return [
        ParametroInicial("rep_semana_umbral", "3", "ENTERO", "Hallazgos",
                         "HAL-01: veces que un caso se repite en una semana para alerta MEDIA.", minimo=2),
        ParametroInicial("rep_semana_alta", "5", "ENTERO", "Hallazgos",
                         "HAL-01: veces en una semana para alerta ALTA.", minimo=2),
        ParametroInicial("rep_mes_umbral", "5", "ENTERO", "Hallazgos",
                         "HAL-01: veces que un caso se repite en un mes para alerta MEDIA.", minimo=2),
        ParametroInicial("rep_mes_alta", "8", "ENTERO", "Hallazgos",
                         "HAL-01: veces en un mes para alerta ALTA.", minimo=2),
        ParametroInicial("pico_semanas", "8", "ENTERO", "Hallazgos",
                         "HAL-02: semanas anteriores con las que se compara el volumen de una estación.", minimo=2),
        ParametroInicial("pico_desviaciones", "2", "DECIMAL", "Hallazgos",
                         "HAL-02: desviaciones estándar sobre la media para considerar un pico.", minimo=0),
        ParametroInicial("pico_minimo", "5", "ENTERO", "Hallazgos",
                         "HAL-02: tickets mínimos en la semana para considerar un pico.", minimo=1),
        ParametroInicial("crecimiento_factor", "1.5", "DECIMAL", "Hallazgos",
                         "HAL-03: veces el promedio de los 3 meses anteriores para categoría en crecimiento.", minimo=1),
        ParametroInicial("crecimiento_minimo", "5", "ENTERO", "Hallazgos",
                         "HAL-03: tickets mínimos en el mes para categoría en crecimiento.", minimo=1),
        ParametroInicial("dias_escalado_alta", "10", "ENTERO", "Hallazgos",
                         "HAL-06: días escalado a partir de los cuales la alerta es ALTA.", minimo=1),
        ParametroInicial("sobrecarga_factor_mediana", "1.5", "DECIMAL", "Hallazgos",
                         "HAL-08: veces la mediana del equipo en abiertos para sobrecarga.", minimo=1),
        ParametroInicial("reincidencia_dias", "7", "ENTERO", "Hallazgos",
                         "KPI-11: días hacia atrás en que se busca el mismo caso.", minimo=1),
        ParametroInicial("correo_jefatura", None, "TEXTO", "Correo",
                         "Destinatarios de los borradores de correo (separados por coma). Puede quedar vacío."),
        ParametroInicial("sla_riesgo_porcentaje", "80", "DECIMAL", "SLA",
                         "Porcentaje del objetivo consumido a partir del cual un ticket abierto está EN RIESGO.",
                         minimo=1, maximo=100),
    ]


KPIS_PREDEFINIDOS = (
    KpiInicial(
        "KPI-01", "Tickets recibidos",
        "Tickets con fecha de apertura en el período.",
        "CONTEO", "tickets", "INFORMATIVO",
    ),
    KpiInicial(
        "KPI-02", "Tickets resueltos",
        "Tickets distintos con un evento de solución en el período.",
        "CONTEO", "tickets", "INFORMATIVO",
    ),
    KpiInicial(
        "KPI-03", "Backlog al corte",
        "Tickets abiertos a la fecha de corte.",
        "CONTEO", "tickets", "MENOR_MEJOR",
    ),
    KpiInicial(
        "KPI-04", "Total gestionados",
        "(Soluciones + escalamientos del período) / tickets recibidos en el "
        "período × 100. Puede superar 100 %.",
        "PORCENTAJE", "%", "MAYOR_MEJOR",
        umbral_verde=80, umbral_amarillo=80, meta=100, critico=True,
    ),
    KpiInicial(
        "KPI-05", "Tasa de escalamiento",
        "Escalamientos / (soluciones + escalamientos) del período × 100.",
        "PORCENTAJE", "%", "MENOR_MEJOR",
        umbral_verde=20, umbral_amarillo=35, critico=True,
    ),
    KpiInicial(
        "KPI-06", "Tiempo de resolución",
        "Mediana de horas de resolución (y P90) de los tickets resueltos en el "
        "período, por prioridad. Los umbrales se definen por prioridad en parámetros.",
        "MEDIANA_TIEMPO", "horas", "MENOR_MEJOR", aproximado=True,
    ),
    KpiInicial(
        "KPI-07", "Cumplimiento SLA",
        "Resueltos dentro del objetivo de su prioridad / resueltos con objetivo × 100.",
        "PORCENTAJE", "%", "MAYOR_MEJOR",
        umbral_verde=90, umbral_amarillo=80, aproximado=True, critico=True,
    ),
    KpiInicial(
        "KPI-08", "Resueltos sin cerrar",
        "Tickets en Resuelto desde hace más de los días configurados / tickets "
        "resueltos en el período × 100. El cierre depende del visto bueno del autor.",
        "PORCENTAJE", "%", "MENOR_MEJOR", umbral_verde=5, critico=True,
    ),
    KpiInicial(
        "KPI-09", "Completitud de clasificación",
        "Tickets resueltos en el período con estación, categoría, causa y tipo de solución "
        "asignados / tickets resueltos en el período × 100.",
        "PORCENTAJE", "%", "MAYOR_MEJOR", umbral_verde=95,
    ),
    KpiInicial(
        "KPI-10", "Uso de «Otros»",
        "Tickets clasificados como OTR-01 / tickets con categoría asignada × 100.",
        "PORCENTAJE", "%", "MENOR_MEJOR", umbral_verde=5,
    ),
    KpiInicial(
        "KPI-11", "Reincidencia",
        "Tickets recibidos cuyo caso (estación + título) se repitió en los días configurados / "
        "tickets recibidos con estación asignada × 100.",
        "PORCENTAJE", "%", "MENOR_MEJOR",
    ),
    KpiInicial(
        "KPI-12", "Reaperturas",
        "Reaperturas del período / tickets resueltos en el período × 100.",
        "PORCENTAJE", "%", "MENOR_MEJOR", umbral_verde=5,
    ),
    KpiInicial(
        "KPI-16", "Tickets sin actualizar",
        "Tickets abiertos sin actualización por más horas que el umbral de su "
        "prioridad / tickets abiertos × 100.",
        "PORCENTAJE", "%", "MENOR_MEJOR",
    ),
    KpiInicial(
        "KPI-17", "Tiempo en escalado",
        "Mediana de horas entre cada escalamiento y su salida del estado Escalado, "
        "para las salidas del período.",
        "MEDIANA_TIEMPO", "horas", "MENOR_MEJOR", aproximado=True,
    ),
)


def _leer_catalogo(nombre: str) -> list[dict]:
    ruta = rutas.directorio_recursos() / CARPETA_CATALOGOS / nombre
    try:
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            return list(csv.DictReader(archivo))
    except OSError as error:
        raise ErrorAplicacion(
            f"No se encontró el catálogo «{nombre}». Reinstale la aplicación.", detalle=repr(error)
        ) from error


def _sembrar_catalogos(conexion: sqlite3.Connection) -> None:
    """Categorías, causas y tipos de solución (IMP-07). Solo si la BD ya tiene esas tablas."""
    tablas = {f[0] for f in conexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "categoria" not in tablas:
        return
    conexion.executemany(
        "INSERT OR IGNORE INTO categoria (codigo, familia, nivel1, nivel2, nivel3, tipo_permitido, "
        "nombre_completo, descripcion) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (f["codigo"], f["familia"], f["nivel1"], f["nivel2"] or None, f["nivel3"] or None,
             f["tipo_permitido"], f["nombre_glpi_completo"], f["descripcion"])
            for f in _leer_catalogo("tipificacion.csv")
        ],
    )
    conexion.executemany(
        "INSERT OR IGNORE INTO causa (codigo, nombre, descripcion) VALUES (?, ?, ?)",
        [(f["codigo"], f["causa"], f["cuando_usar"]) for f in _leer_catalogo("causas.csv")],
    )
    conexion.executemany(
        "INSERT OR IGNORE INTO tipo_solucion (codigo, nombre, nota) VALUES (?, ?, ?)",
        [(f["codigo"], f["tipo_solucion"], f["nota"] or None) for f in _leer_catalogo("tipos_solucion.csv")],
    )


def sembrar(conexion: sqlite3.Connection) -> None:
    """Inserta los parámetros, KPIs y catálogos que falten, en una sola transacción."""
    with conexion:
        _sembrar_catalogos(conexion)
        conexion.executemany(
            "INSERT OR IGNORE INTO parametro "
            "(clave, valor, tipo, grupo, descripcion, minimo, maximo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (p.clave, p.valor, p.tipo, p.grupo, p.descripcion, p.minimo, p.maximo)
                for p in _parametros()
            ],
        )
        conexion.executemany(
            "INSERT OR IGNORE INTO kpi_definicion "
            "(codigo, nombre, descripcion, tipo_calculo, calculo_especial, unidad, "
            " direccion, umbral_verde, umbral_amarillo, meta, aproximado, critico, "
            " predefinido, visible_dashboard, orden) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?)",
            [
                (
                    k.codigo, k.nombre, k.descripcion, k.tipo_calculo, k.codigo,
                    k.unidad, k.direccion, k.umbral_verde, k.umbral_amarillo, k.meta,
                    int(k.aproximado), int(k.critico), orden,
                )
                for orden, k in enumerate(KPIS_PREDEFINIDOS, start=1)
            ],
        )
