"""SLA por ticket (spec 09) y objetivos por prioridad (KPI-07).

La exportación no trae fecha de vencimiento: el objetivo de cada ticket es el
parámetro `sla_horas_<prioridad>`, que define el coordinador. Estados:
- CUMPLIDO / INCUMPLIDO: ticket resuelto dentro o fuera del objetivo;
- EN_RIESGO: abierto con al menos `sla_riesgo_porcentaje` % del objetivo consumido;
- INCUMPLIDO también para un abierto que ya superó el objetivo;
- EN_PLAZO: abierto con tiempo de sobra;
- SIN_OBJETIVO: su prioridad no tiene objetivo definido.
Los tiempos son aproximados y no descuentan la espera (RN-03, RN-06).
"""

import sqlite3
from datetime import datetime

from core import parametros
from core.dominio import PRIORIDADES

CUMPLIDO = "CUMPLIDO"
INCUMPLIDO = "INCUMPLIDO"
EN_RIESGO = "EN_RIESGO"
EN_PLAZO = "EN_PLAZO"
SIN_OBJETIVO = "SIN_OBJETIVO"
NOMBRES = {
    CUMPLIDO: "✔ Cumplido", INCUMPLIDO: "✖ Incumplido", EN_RIESGO: "▲ En riesgo",
    EN_PLAZO: "En plazo", SIN_OBJETIVO: "Sin objetivo",
}


def objetivos(conexion: sqlite3.Connection) -> dict[int, float | None]:
    """Nivel de prioridad → horas objetivo (None si no está definido)."""
    return {
        p.nivel: parametros.decimal_opcional(conexion, f"sla_horas_{p.clave}") for p in PRIORIDADES
    }


def a_tiempo(horas_resolucion: float, objetivo_horas: float) -> bool:
    return horas_resolucion <= objetivo_horas


def estado(
    fecha_apertura: datetime,
    fecha_solucion: datetime | None,
    objetivo_horas: float | None,
    ahora: datetime,
    riesgo_porcentaje: float,
) -> tuple[str, float | None]:
    """Estado SLA y horas transcurridas (hasta la solución o hasta ahora)."""
    fin = fecha_solucion or ahora
    horas = max(0.0, (fin - fecha_apertura).total_seconds() / 3600)
    if objetivo_horas is None:
        return SIN_OBJETIVO, round(horas, 2)
    if fecha_solucion is not None:
        return (CUMPLIDO if a_tiempo(horas, objetivo_horas) else INCUMPLIDO), round(horas, 2)
    if horas > objetivo_horas:
        return INCUMPLIDO, round(horas, 2)
    if horas >= objetivo_horas * riesgo_porcentaje / 100:
        return EN_RIESGO, round(horas, 2)
    return EN_PLAZO, round(horas, 2)
