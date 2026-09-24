"""Registro técnico en logs/app.log con rotación (RNF-11)."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

NOMBRE_LOG = "app.log"
TAMANO_MAXIMO_BYTES = 1_000_000
COPIAS_ROTACION = 5
FORMATO = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class _ManejadorAnalizador(RotatingFileHandler):
    """Identifica el manejador propio para poder reemplazarlo sin duplicar."""


def configurar(carpeta_logs: Path, nivel: str) -> Path:
    """Envía el log raíz a carpeta_logs/app.log. Se puede llamar varias veces."""
    raiz = logging.getLogger()
    for manejador in list(raiz.handlers):
        if isinstance(manejador, _ManejadorAnalizador):
            raiz.removeHandler(manejador)
            manejador.close()
    ruta = carpeta_logs / NOMBRE_LOG
    manejador = _ManejadorAnalizador(
        ruta,
        maxBytes=TAMANO_MAXIMO_BYTES,
        backupCount=COPIAS_ROTACION,
        encoding="utf-8",
    )
    manejador.setFormatter(logging.Formatter(FORMATO))
    raiz.addHandler(manejador)
    raiz.setLevel(nivel)
    return ruta
