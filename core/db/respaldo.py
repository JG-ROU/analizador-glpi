"""Respaldos de la BD: antes de importar, diario, retención y restauración (RNF-04, RNF-15).

Las copias usan la API de respaldo de SQLite, que produce una copia consistente
aunque la BD esté abierta en modo WAL. Los archivos se llaman
analizador_<motivo>_AAAAMMDD_HHMMSS.db y la fecha del nombre es la que cuenta
para la retención.
"""

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from core import historial, reloj, seguridad
from core.errores import ErrorAplicacion, ErrorValidacion
from core.seguridad import Sesion

log = logging.getLogger(__name__)

PREFIJO = "analizador"
MOTIVO_DIARIO = "diario"
MOTIVO_IMPORTACION = "antes_importacion"
MOTIVO_RESTAURACION = "antes_restauracion"

_PATRON = re.compile(rf"^{PREFIJO}_([a-z0-9_]+?)_(\d{{8}}_\d{{6}})(?:_\d+)?\.db$")
_FORMATO_FECHA = "%Y%m%d_%H%M%S"


@dataclass(frozen=True)
class Respaldo:
    ruta: Path
    motivo: str
    fecha: datetime
    tamano_bytes: int


def respaldar(conexion: sqlite3.Connection, carpeta: Path, motivo: str) -> Path:
    """Copia la BD abierta a la carpeta de respaldos y devuelve la ruta creada."""
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = _destino_libre(carpeta, motivo)
        copia = sqlite3.connect(destino)
        try:
            conexion.backup(copia)
        finally:
            copia.close()
    except (sqlite3.Error, OSError) as error:
        raise ErrorAplicacion(
            f"No se pudo crear el respaldo de la base de datos en «{carpeta}».",
            detalle=repr(error),
        ) from error
    log.info("Respaldo creado: %s", destino)
    return destino


def respaldar_antes_de_importar(
    conexion: sqlite3.Connection, carpeta: Path, retencion_dias: int
) -> Path:
    ruta = respaldar(conexion, carpeta, MOTIVO_IMPORTACION)
    aplicar_retencion(carpeta, retencion_dias)
    return ruta


def respaldo_diario(
    conexion: sqlite3.Connection, carpeta: Path, retencion_dias: int
) -> Path | None:
    """Crea el respaldo del día si todavía no existe. Devuelve None si ya existía."""
    hoy = reloj.ahora().date()
    ya_existe = any(
        r.motivo == MOTIVO_DIARIO and r.fecha.date() == hoy for r in listar(carpeta)
    )
    ruta = None if ya_existe else respaldar(conexion, carpeta, MOTIVO_DIARIO)
    aplicar_retencion(carpeta, retencion_dias)
    return ruta


def listar(carpeta: Path) -> list[Respaldo]:
    """Respaldos de la carpeta, del más reciente al más antiguo."""
    if not carpeta.is_dir():
        return []
    respaldos = []
    for ruta in carpeta.glob(f"{PREFIJO}_*.db"):
        coincidencia = _PATRON.match(ruta.name)
        if not coincidencia:
            continue
        fecha = datetime.strptime(coincidencia.group(2), _FORMATO_FECHA)
        respaldos.append(Respaldo(ruta, coincidencia.group(1), fecha, ruta.stat().st_size))
    respaldos.sort(key=lambda r: (r.fecha, r.ruta.name), reverse=True)
    return respaldos


def aplicar_retencion(carpeta: Path, dias: int) -> list[Path]:
    """Borra los respaldos con más de `dias` días; nunca borra el más reciente."""
    limite = reloj.ahora() - timedelta(days=dias)
    borrados = []
    for respaldo in listar(carpeta)[1:]:
        if respaldo.fecha < limite:
            try:
                respaldo.ruta.unlink()
            except OSError:
                log.warning("No se pudo borrar el respaldo vencido %s", respaldo.ruta, exc_info=True)
                continue
            borrados.append(respaldo.ruta)
    if borrados:
        log.info("Retención: %d respaldos vencidos borrados", len(borrados))
    return borrados


def restaurar(
    conexion: sqlite3.Connection,
    sesion: Sesion,
    ruta_respaldo: Path,
    carpeta_respaldos: Path,
) -> Path:
    """Reemplaza el contenido de la BD por el del respaldo. Solo el coordinador.

    Antes se respalda la BD actual; se devuelve la ruta de ese respaldo previo.
    Después se migra el contenido restaurado a la versión actual.
    """
    # Importación diferida: migrador importa este módulo
    from core.db import migrador, semilla

    seguridad.exigir_coordinador(sesion)
    version = _validar_respaldo(ruta_respaldo, migrador.descubrir()[-1].version)
    previo = respaldar(conexion, carpeta_respaldos, MOTIVO_RESTAURACION)
    try:
        origen = sqlite3.connect(_uri_solo_lectura(ruta_respaldo), uri=True)
        try:
            origen.backup(conexion)
        finally:
            origen.close()
    except sqlite3.Error as error:
        raise ErrorAplicacion(
            "No se pudo restaurar el respaldo. La base de datos anterior quedó "
            f"guardada en «{previo.name}».",
            detalle=repr(error),
        ) from error
    migrador.migrar(conexion, carpeta_respaldos)
    semilla.sembrar(conexion)
    usuario_existe = conexion.execute(
        "SELECT 1 FROM usuario WHERE id = ?", (sesion.usuario_id,)
    ).fetchone()
    with conexion:
        historial.registrar(
            conexion,
            entidad="base_datos",
            entidad_id=None,
            accion="RESTAURAR",
            usuario_id=sesion.usuario_id if usuario_existe else None,
            valor_nuevo=ruta_respaldo.name,
            nota=f"Restaurado por {sesion.nombre} desde un respaldo de la versión "
            f"{version}. Respaldo previo: {previo.name}",
        )
    log.info("BD restaurada desde %s; respaldo previo %s", ruta_respaldo, previo)
    return previo


def _destino_libre(carpeta: Path, motivo: str) -> Path:
    base = f"{PREFIJO}_{motivo}_{reloj.ahora():{_FORMATO_FECHA}}"
    destino = carpeta / f"{base}.db"
    numero = 2
    while destino.exists():
        destino = carpeta / f"{base}_{numero}.db"
        numero += 1
    return destino


def _uri_solo_lectura(ruta: Path) -> str:
    return f"{ruta.resolve().as_uri()}?mode=ro"


def _validar_respaldo(ruta: Path, version_maxima: int) -> int:
    """Comprueba que el archivo sea una BD íntegra del Analizador y devuelve su versión."""
    if not ruta.is_file():
        raise ErrorValidacion(f"No existe el archivo de respaldo «{ruta}».")
    try:
        origen = sqlite3.connect(_uri_solo_lectura(ruta), uri=True)
        try:
            integridad = origen.execute("PRAGMA integrity_check").fetchone()[0]
            version = origen.execute("PRAGMA user_version").fetchone()[0]
            tablas = {
                fila[0]
                for fila in origen.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        finally:
            origen.close()
    except sqlite3.Error as error:
        raise ErrorValidacion(
            "El archivo elegido no es un respaldo válido del Analizador GLPI.",
            detalle=repr(error),
        ) from error
    if integridad != "ok":
        raise ErrorValidacion(
            "El respaldo está dañado y no se puede restaurar.", detalle=integridad
        )
    if version < 1 or not {"migracion", "ticket", "usuario"} <= tablas:
        raise ErrorValidacion(
            "El archivo elegido no es un respaldo válido del Analizador GLPI."
        )
    if version > version_maxima:
        raise ErrorValidacion(
            "El respaldo fue creado por una versión más reciente del Analizador GLPI "
            "y no se puede restaurar con esta versión."
        )
    return version
