"""Contrato común de las fuentes de datos (RNF-14).

Una fuente entrega los datos crudos en bloques de DataFrame con columnas de texto,
tal como vienen del origen. El mapeo a campos internos y la validación se hacen
después, igual para cualquier fuente.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from datetime import datetime

import pandas as pd

# Columna agregada por las fuentes con el número de fila del origen, para los mensajes
COLUMNA_FILA = "_fila"


class FuenteDatos(ABC):
    @abstractmethod
    def obtener_tickets(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> Iterator[pd.DataFrame]:
        """Bloques de tickets crudos. Una fuente que no puede filtrar por fecha
        (como un CSV ya exportado) entrega todas sus filas."""

    @abstractmethod
    def obtener_seguimientos(self, ids: Iterable[int]) -> Iterator[pd.DataFrame]:
        """Bloques de seguimientos y tareas de los tickets indicados (Fase 3)."""
