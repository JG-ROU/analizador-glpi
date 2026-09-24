"""Conexión a SQLite con las convenciones del proyecto (spec 04)."""

import sqlite3
from pathlib import Path

from core.errores import ErrorAplicacion

ESPERA_BLOQUEO_MS = 5000


def conectar(ruta: Path) -> sqlite3.Connection:
    """Abre la BD con claves foráneas, modo WAL y filas accesibles por nombre."""
    try:
        conexion = sqlite3.connect(ruta)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute(f"PRAGMA busy_timeout = {ESPERA_BLOQUEO_MS}")
        conexion.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error as error:
        raise ErrorAplicacion(
            f"No se pudo abrir la base de datos «{ruta}». "
            "Verifique que el archivo no esté dañado ni abierto por otro programa.",
            detalle=repr(error),
        ) from error
    return conexion
