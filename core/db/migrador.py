"""Migraciones versionadas del esquema (RNF-13, RNF-15).

Cada migración es un archivo `NNN_nombre.sql` en core/db/migraciones/. La versión
aplicada se guarda en `PRAGMA user_version` y en la tabla `migracion`. Cada
migración corre en su propia transacción: si falla, la BD queda como estaba.
Antes de migrar una BD con datos se crea un respaldo.
"""

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from core import reloj
from core.db import respaldo
from core.errores import ErrorAplicacion

log = logging.getLogger(__name__)

CARPETA_MIGRACIONES = Path(__file__).resolve().parent / "migraciones"
_PATRON_ARCHIVO = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")


@dataclass(frozen=True)
class Migracion:
    version: int
    nombre: str
    archivo: Path


def descubrir(carpeta: Path = CARPETA_MIGRACIONES) -> list[Migracion]:
    """Lista las migraciones ordenadas; exige versiones consecutivas desde 1."""
    migraciones = []
    for archivo in carpeta.glob("*.sql"):
        coincidencia = _PATRON_ARCHIVO.match(archivo.name)
        if not coincidencia:
            raise ErrorAplicacion(
                "La instalación tiene un archivo de migración con nombre inválido.",
                detalle=str(archivo),
            )
        migraciones.append(
            Migracion(int(coincidencia.group(1)), coincidencia.group(2), archivo)
        )
    migraciones.sort(key=lambda m: m.version)
    versiones = [m.version for m in migraciones]
    if versiones != list(range(1, len(versiones) + 1)):
        raise ErrorAplicacion(
            "La instalación tiene migraciones faltantes o repetidas.",
            detalle=f"Versiones encontradas: {versiones}",
        )
    return migraciones


def version_actual(conexion: sqlite3.Connection) -> int:
    return conexion.execute("PRAGMA user_version").fetchone()[0]


def migrar(
    conexion: sqlite3.Connection,
    carpeta_respaldos: Path,
    carpeta_migraciones: Path = CARPETA_MIGRACIONES,
) -> int:
    """Aplica las migraciones pendientes y devuelve la versión final."""
    migraciones = descubrir(carpeta_migraciones)
    actual = version_actual(conexion)
    ultima = migraciones[-1].version if migraciones else 0
    if actual > ultima:
        raise ErrorAplicacion(
            "La base de datos fue creada por una versión más reciente del "
            "Analizador GLPI. Use la versión más reciente de la aplicación.",
            detalle=f"BD en versión {actual}; la aplicación conoce hasta {ultima}",
        )
    pendientes = [m for m in migraciones if m.version > actual]
    if not pendientes:
        return actual
    if actual > 0:
        ruta = respaldo.respaldar(conexion, carpeta_respaldos, f"antes_migracion_v{actual}")
        log.info("Respaldo previo a la migración: %s", ruta)
    for migracion in pendientes:
        _aplicar(conexion, migracion)
    return pendientes[-1].version


def _aplicar(conexion: sqlite3.Connection, migracion: Migracion) -> None:
    sql = migracion.archivo.read_text(encoding="utf-8")
    nombre = migracion.nombre.replace("'", "''")
    guion = (
        "BEGIN;\n"
        f"{sql}\n;\n"
        "INSERT INTO migracion (version, nombre, aplicada_en) "
        f"VALUES ({migracion.version}, '{nombre}', '{reloj.ahora().isoformat(sep=' ')}');\n"
        f"PRAGMA user_version = {migracion.version};\n"
        "COMMIT;"
    )
    try:
        conexion.executescript(guion)
    except sqlite3.Error as error:
        if conexion.in_transaction:
            conexion.rollback()
        raise ErrorAplicacion(
            f"No se pudo actualizar la base de datos a la versión {migracion.version}. "
            "Los datos no se modificaron.",
            detalle=f"{migracion.archivo.name}: {error!r}",
        ) from error
    log.info("Migración aplicada: %03d_%s", migracion.version, migracion.nombre)
