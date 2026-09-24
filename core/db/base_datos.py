"""Apertura de la BD de la aplicación: conexión, migraciones y semillas."""

import sqlite3
from pathlib import Path

from core.db import conexion as conexion_db
from core.db import migrador, semilla


def abrir(ruta: Path, carpeta_respaldos: Path) -> sqlite3.Connection:
    """Abre (o crea) la BD, la lleva a la última versión y completa las semillas."""
    conexion = conexion_db.conectar(ruta)
    try:
        migrador.migrar(conexion, carpeta_respaldos)
        semilla.sembrar(conexion)
    except Exception:
        conexion.close()
        raise
    return conexion
