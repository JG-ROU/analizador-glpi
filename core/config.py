"""Lectura y validación de config.ini: parámetros de arranque (RNF-10).

Los umbrales que el usuario edita en pantalla no van aquí, sino en la tabla `parametro`.
"""

import codecs
import configparser
import shutil
from dataclasses import dataclass
from pathlib import Path

from core.errores import ErrorConfiguracion
from core.turnos import Franja, interpretar_franja, validar_franjas

NOMBRE_ARCHIVO = "config.ini"
NOMBRE_PLANTILLA = "config.ini.ejemplo"
NIVELES_LOG = ("DEBUG", "INFO", "WARNING", "ERROR")


@dataclass(frozen=True)
class ConfigRutas:
    base_datos: Path
    respaldos: Path
    exportaciones: Path
    logs: Path

    def carpetas(self) -> tuple[Path, ...]:
        """Carpetas que deben existir al arrancar (RNF-03)."""
        return (self.base_datos.parent, self.respaldos, self.exportaciones, self.logs)


@dataclass(frozen=True)
class ConfigImportacion:
    separador_por_defecto: str
    codificacion_por_defecto: str
    formato_fecha: str
    tamano_bloque: int


@dataclass(frozen=True)
class ConfigGeneral:
    nivel_log: str
    retencion_respaldos: int


@dataclass(frozen=True)
class Config:
    archivo: Path
    rutas: ConfigRutas
    importacion: ConfigImportacion
    turnos: tuple[Franja, ...]
    general: ConfigGeneral


def asegurar_archivo(directorio_base: Path, directorio_recursos: Path) -> Path:
    """Devuelve la ruta de config.ini; si falta, lo crea copiando la plantilla."""
    destino = directorio_base / NOMBRE_ARCHIVO
    if destino.exists():
        return destino
    plantilla = directorio_recursos / NOMBRE_PLANTILLA
    if not plantilla.exists():
        raise ErrorConfiguracion(
            f"No se encontró {NOMBRE_ARCHIVO} ni la plantilla {NOMBRE_PLANTILLA}. "
            "Reinstale la aplicación."
        )
    try:
        shutil.copyfile(plantilla, destino)
    except OSError as error:
        raise ErrorConfiguracion(
            f"No se pudo crear {destino}. Verifique los permisos de escritura.",
            detalle=repr(error),
        ) from error
    return destino


def cargar(archivo: Path, directorio_base: Path) -> Config:
    """Lee y valida config.ini. Las rutas relativas se resuelven desde directorio_base."""
    lector = configparser.ConfigParser(interpolation=None)
    lector.optionxform = str  # conserva mayúsculas y tildes de los nombres de turno
    try:
        lector.read_string(_leer_texto(archivo), source=str(archivo))
    except configparser.Error as error:
        raise ErrorConfiguracion(
            f"{NOMBRE_ARCHIVO} tiene un error de formato. Revise el archivo.",
            detalle=str(error),
        ) from error

    rutas = ConfigRutas(
        base_datos=_ruta(lector, "rutas", "base_datos", directorio_base),
        respaldos=_ruta(lector, "rutas", "respaldos", directorio_base),
        exportaciones=_ruta(lector, "rutas", "exportaciones", directorio_base),
        logs=_ruta(lector, "rutas", "logs", directorio_base),
    )
    importacion = ConfigImportacion(
        separador_por_defecto=_separador(lector),
        codificacion_por_defecto=_codificacion(lector),
        formato_fecha=_obtener(lector, "importacion", "formato_fecha"),
        tamano_bloque=_entero(lector, "importacion", "tamano_bloque", minimo=100),
    )
    general = ConfigGeneral(
        nivel_log=_nivel_log(lector),
        retencion_respaldos=_entero(lector, "general", "retencion_respaldos", minimo=1),
    )
    return Config(
        archivo=archivo,
        rutas=rutas,
        importacion=importacion,
        turnos=_turnos(lector),
        general=general,
    )


def _leer_texto(archivo: Path) -> str:
    try:
        datos = archivo.read_bytes()
    except OSError as error:
        raise ErrorConfiguracion(
            f"No se pudo leer {archivo}.", detalle=repr(error)
        ) from error
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Archivo guardado por un editor en la codificación de Windows
        return datos.decode("cp1252")


def _obtener(lector: configparser.ConfigParser, seccion: str, clave: str) -> str:
    if not lector.has_section(seccion):
        raise ErrorConfiguracion(
            f"Falta la sección [{seccion}] en {NOMBRE_ARCHIVO}."
        )
    valor = lector.get(seccion, clave, fallback="").strip()
    if not valor:
        raise ErrorConfiguracion(
            f"Falta el valor «{clave}» en la sección [{seccion}] de {NOMBRE_ARCHIVO}."
        )
    return valor


def _entero(
    lector: configparser.ConfigParser, seccion: str, clave: str, minimo: int
) -> int:
    texto = _obtener(lector, seccion, clave)
    try:
        valor = int(texto)
    except ValueError:
        valor = minimo - 1
    if valor < minimo:
        raise ErrorConfiguracion(
            f"El valor «{clave}» de [{seccion}] debe ser un número entero mayor o "
            f"igual a {minimo}; tiene «{texto}»."
        )
    return valor


def _ruta(
    lector: configparser.ConfigParser, seccion: str, clave: str, base: Path
) -> Path:
    ruta = Path(_obtener(lector, seccion, clave))
    return ruta if ruta.is_absolute() else base / ruta


def _separador(lector: configparser.ConfigParser) -> str:
    valor = _obtener(lector, "importacion", "separador_por_defecto")
    if len(valor) != 1:
        raise ErrorConfiguracion(
            "El «separador_por_defecto» de [importacion] debe ser un solo carácter, "
            f"por ejemplo ; o ,. Tiene «{valor}»."
        )
    return valor


def _codificacion(lector: configparser.ConfigParser) -> str:
    valor = _obtener(lector, "importacion", "codificacion_por_defecto")
    try:
        codecs.lookup(valor)
    except LookupError as error:
        raise ErrorConfiguracion(
            f"La codificación «{valor}» de [importacion] no existe. "
            "Use utf-8-sig, utf-8 o latin-1."
        ) from error
    return valor


def _nivel_log(lector: configparser.ConfigParser) -> str:
    valor = _obtener(lector, "general", "nivel_log").upper()
    if valor not in NIVELES_LOG:
        raise ErrorConfiguracion(
            f"El «nivel_log» de [general] debe ser uno de {', '.join(NIVELES_LOG)}; "
            f"tiene «{valor}»."
        )
    return valor


def _turnos(lector: configparser.ConfigParser) -> tuple[Franja, ...]:
    if not lector.has_section("turnos"):
        raise ErrorConfiguracion(f"Falta la sección [turnos] en {NOMBRE_ARCHIVO}.")
    franjas = tuple(
        interpretar_franja(turno, texto) for turno, texto in lector.items("turnos")
    )
    validar_franjas(franjas)
    return franjas
