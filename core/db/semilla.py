"""Datos iniciales: parámetros y KPIs predefinidos de la Fase 1 (spec 05).

Se insertan solo si no existen, así que nunca sobrescriben lo que el usuario editó.
Los valores que la especificación no fija (objetivos de SLA, umbrales de KPI-06)
quedan vacíos: los define el coordinador en el asistente o en Configuración.
"""

import sqlite3
from dataclasses import dataclass

from core.dominio import PRIORIDADES

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


def sembrar(conexion: sqlite3.Connection) -> None:
    """Inserta los parámetros y KPIs que falten, en una sola transacción."""
    with conexion:
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
