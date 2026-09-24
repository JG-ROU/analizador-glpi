"""Ubicación de las carpetas de la aplicación (RNF-01, RNF-03).

Con el ejecutable, config.ini, data/, logs/ y exportaciones/ viven junto al .exe,
no en la carpeta temporal donde PyInstaller descomprime el código.
"""

import sys
from collections.abc import Iterable
from pathlib import Path

from core.errores import ErrorAplicacion

_RAIZ_PROYECTO = Path(__file__).resolve().parent.parent


def empaquetado() -> bool:
    """Indica si se está ejecutando desde el .exe generado con PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def directorio_base() -> Path:
    """Carpeta de los datos del usuario: junto al .exe o la raíz del proyecto."""
    if empaquetado():
        return Path(sys.executable).resolve().parent
    return _RAIZ_PROYECTO


def directorio_recursos() -> Path:
    """Carpeta de los recursos incluidos en el ejecutable (plantillas, estilos, íconos)."""
    if empaquetado():
        return Path(getattr(sys, "_MEIPASS", directorio_base()))
    return _RAIZ_PROYECTO


def crear_carpetas(carpetas: Iterable[Path]) -> None:
    """Crea las carpetas que falten."""
    for carpeta in carpetas:
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ErrorAplicacion(
                f"No se pudo crear la carpeta «{carpeta}». "
                "Verifique que tiene permisos de escritura en esa ubicación.",
                detalle=repr(error),
            ) from error
