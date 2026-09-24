"""Secuencia de arranque sin interfaz: config.ini, carpetas, logs, base de datos
y respaldo diario."""

import logging
import sqlite3
from dataclasses import dataclass

from core import config, registro, rutas
from core.db import base_datos, respaldo
from core.version import VERSION

log = logging.getLogger(__name__)

CARPETA_LOGS_INICIAL = "logs"


@dataclass
class Contexto:
    """Lo que la interfaz necesita después de arrancar."""

    config: config.Config
    conexion: sqlite3.Connection


def arrancar() -> Contexto:
    """Prepara el entorno y devuelve la configuración y la BD lista para usar."""
    base = rutas.directorio_base()
    # Log provisional para registrar errores de config.ini antes de leerlo
    carpeta_inicial = base / CARPETA_LOGS_INICIAL
    rutas.crear_carpetas([carpeta_inicial])
    registro.configurar(carpeta_inicial, "INFO")

    archivo = config.asegurar_archivo(base, rutas.directorio_recursos())
    cfg = config.cargar(archivo, base)
    rutas.crear_carpetas(cfg.rutas.carpetas())
    registro.configurar(cfg.rutas.logs, cfg.general.nivel_log)
    log.info("Inicio de Analizador GLPI %s en %s", VERSION, base)

    conexion = base_datos.abrir(cfg.rutas.base_datos, cfg.rutas.respaldos)
    try:
        respaldo.respaldo_diario(
            conexion, cfg.rutas.respaldos, cfg.general.retencion_respaldos
        )
    except Exception:
        conexion.close()
        raise
    return Contexto(config=cfg, conexion=conexion)
