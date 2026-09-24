"""Objetivos de SLA por prioridad (spec 09) para KPI-07.

La exportación no trae fecha de vencimiento, así que el objetivo de cada ticket
es el parámetro `sla_horas_<prioridad>`. Los valores los define el coordinador;
la aplicación no los supone. El estado SLA por ticket (EN_RIESGO, etc.) se
agrega en la Fase 2.
"""

import sqlite3

from core import parametros
from core.dominio import PRIORIDADES


def objetivos(conexion: sqlite3.Connection) -> dict[int, float | None]:
    """Nivel de prioridad → horas objetivo (None si no está definido)."""
    return {
        p.nivel: parametros.decimal_opcional(conexion, f"sla_horas_{p.clave}") for p in PRIORIDADES
    }


def a_tiempo(horas_resolucion: float, objetivo_horas: float) -> bool:
    return horas_resolucion <= objetivo_horas
