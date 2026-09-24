"""Hora local de la operación.

Todas las fechas de la aplicación están en hora de Colombia (America/Bogota,
UTC-5, sin horario de verano) y se guardan sin zona. Usar siempre `ahora()`
en lugar de `datetime.now()` para que las pruebas puedan fijar la hora.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

ZONA_OPERACION = ZoneInfo("America/Bogota")


def ahora() -> datetime:
    """Fecha y hora actuales en Bogotá, sin zona y sin microsegundos."""
    return datetime.now(ZONA_OPERACION).replace(tzinfo=None, microsecond=0)
