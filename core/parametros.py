"""Lectura de la tabla `parametro` (umbrales editables en pantalla).

La edición con historial se agrega con la pantalla de Configuración (T21).
"""

import sqlite3

from core.errores import ErrorConfiguracion


def valor(conexion: sqlite3.Connection, clave: str) -> str | None:
    fila = conexion.execute("SELECT valor FROM parametro WHERE clave = ?", (clave,)).fetchone()
    if fila is None:
        raise ErrorConfiguracion(f"No existe el parámetro «{clave}».")
    return fila[0]


def entero(conexion: sqlite3.Connection, clave: str) -> int:
    texto = valor(conexion, clave)
    try:
        return int(texto)
    except (TypeError, ValueError):
        raise ErrorConfiguracion(
            f"El parámetro «{clave}» no tiene un número entero válido. Revíselo en Configuración."
        ) from None


def decimal_opcional(conexion: sqlite3.Connection, clave: str) -> float | None:
    """None si el parámetro está vacío (por ejemplo, un objetivo de SLA sin definir)."""
    texto = valor(conexion, clave)
    if texto is None or not texto.strip():
        return None
    try:
        return float(texto)
    except ValueError:
        raise ErrorConfiguracion(
            f"El parámetro «{clave}» no tiene un número válido. Revíselo en Configuración."
        ) from None
