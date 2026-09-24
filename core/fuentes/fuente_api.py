"""Fuente de datos por la API REST de GLPI (RNF-14). Se implementa en la Fase 4.

Cumple el mismo contrato que FuenteCSV (core/fuentes/base.py): entrega bloques de
DataFrame con columnas de texto, que después pasan por el mismo mapeo, validación
y carga incremental. Así, agregar la API no cambia el resto de la aplicación.
Las credenciales no se guardarán en el aplicativo (RNF-07).
"""

from collections.abc import Iterable, Iterator
from datetime import datetime

import pandas as pd

from core.errores import ErrorAplicacion
from core.fuentes.base import FuenteDatos

MENSAJE_FASE_4 = "La conexión con la API REST de GLPI se implementa en la Fase 4."


class FuenteAPI(FuenteDatos):
    def __init__(self, url_base: str):
        self.url_base = url_base

    def obtener_tickets(self, desde: datetime | None = None, hasta: datetime | None = None) -> Iterator[pd.DataFrame]:
        raise ErrorAplicacion(MENSAJE_FASE_4)

    def obtener_seguimientos(self, ids: Iterable[int]) -> Iterator[pd.DataFrame]:
        raise ErrorAplicacion(MENSAJE_FASE_4)
