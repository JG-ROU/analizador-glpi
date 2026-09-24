"""Días hábiles y festivos (RN-05).

La operación es 24/7: los SLA de tickets usan horas calendario. Los días hábiles
se usan donde una regla lo pide (por ejemplo, "revisión en 2 días hábiles").

`festivos_colombia` calcula los festivos de ley (Ley 51 de 1983, "Ley Emiliani")
solo como **propuesta**: el coordinador la confirma antes de guardarla en la tabla
`festivo`, que es la que usan los cálculos.
"""

import sqlite3
from datetime import date, timedelta

LUNES = 0
SABADO = 5


def festivos_guardados(conexion: sqlite3.Connection) -> set[date]:
    return {date.fromisoformat(f[0]) for f in conexion.execute("SELECT fecha FROM festivo")}


def es_habil(dia: date, festivos: set[date]) -> bool:
    return dia.weekday() < SABADO and dia not in festivos


def dias_habiles_entre(inicio: date, fin: date, festivos: set[date]) -> int:
    """Días hábiles en [inicio, fin): incluye el inicio y excluye el fin."""
    total = 0
    dia = inicio
    while dia < fin:
        total += es_habil(dia, festivos)
        dia += timedelta(days=1)
    return total


def sumar_dias_habiles(inicio: date, dias: int, festivos: set[date]) -> date:
    """El día hábil que está `dias` días hábiles después de `inicio`."""
    dia = inicio
    restantes = dias
    while restantes > 0:
        dia += timedelta(days=1)
        if es_habil(dia, festivos):
            restantes -= 1
    return dia


# --- Propuesta de festivos de Colombia ---

def domingo_de_pascua(anio: int) -> date:
    """Algoritmo anónimo gregoriano (Meeus/Jones/Butcher)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _siguiente_lunes(dia: date) -> date:
    return dia + timedelta(days=(LUNES - dia.weekday()) % 7)


def festivos_colombia(anio: int) -> list[tuple[date, str]]:
    """Festivos nacionales de Colombia del año, ordenados por fecha."""
    pascua = domingo_de_pascua(anio)
    fijos = [
        (date(anio, 1, 1), "Año Nuevo"),
        (pascua - timedelta(days=3), "Jueves Santo"),
        (pascua - timedelta(days=2), "Viernes Santo"),
        (date(anio, 5, 1), "Día del Trabajo"),
        (date(anio, 7, 20), "Día de la Independencia"),
        (date(anio, 8, 7), "Batalla de Boyacá"),
        (date(anio, 12, 8), "Inmaculada Concepción"),
        (date(anio, 12, 25), "Navidad"),
    ]
    trasladables = [
        (date(anio, 1, 6), "Reyes Magos"),
        (date(anio, 3, 19), "San José"),
        (date(anio, 6, 29), "San Pedro y San Pablo"),
        (date(anio, 8, 15), "Asunción de la Virgen"),
        (date(anio, 10, 12), "Día de la Raza"),
        (date(anio, 11, 1), "Todos los Santos"),
        (date(anio, 11, 11), "Independencia de Cartagena"),
        # Religiosos móviles: se celebran el lunes siguiente a su fecha
        (pascua + timedelta(days=39), "Ascensión del Señor"),
        (pascua + timedelta(days=60), "Corpus Christi"),
        (pascua + timedelta(days=68), "Sagrado Corazón"),
    ]
    festivos = fijos + [(_siguiente_lunes(dia), nombre) for dia, nombre in trasladables]
    return sorted(festivos)
