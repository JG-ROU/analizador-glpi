"""Eventos detectados entre importaciones (IMP-06). Funciones puras.

Como el CSV solo trae el estado actual, un evento se detecta al comparar el
estado guardado con el de la nueva importación. La fecha del evento es la
«Última actualización» de la fila.
"""

from dataclasses import dataclass
from datetime import datetime

from core.dominio import CERRADO, ESCALADO, ESTADOS_SOLUCIONADOS

ESCALAMIENTO = "ESCALAMIENTO"
SALIDA_ESCALADO = "SALIDA_ESCALADO"
SOLUCION = "SOLUCION"
CIERRE = "CIERRE"
REAPERTURA = "REAPERTURA"

TRANSICION = "TRANSICION"
PRIMERA_VEZ = "PRIMERA_VEZ"


def eventos_de_transicion(anterior: str | None, nuevo: str) -> list[str]:
    """Eventos al pasar del estado `anterior` al `nuevo` (códigos normalizados).

    Con `anterior` None el ticket se ve por primera vez: se registran los eventos
    que explican su estado actual.
    """
    if anterior is None:
        if nuevo == ESCALADO:
            return [ESCALAMIENTO]
        if nuevo == CERRADO:
            return [SOLUCION, CIERRE]
        if nuevo in ESTADOS_SOLUCIONADOS:
            return [SOLUCION]
        return []
    eventos = []
    if anterior == ESCALADO and nuevo != ESCALADO:
        eventos.append(SALIDA_ESCALADO)
    if anterior not in ESTADOS_SOLUCIONADOS and nuevo in ESTADOS_SOLUCIONADOS:
        eventos.append(SOLUCION)
    if anterior != CERRADO and nuevo == CERRADO:
        eventos.append(CIERRE)
    if anterior in ESTADOS_SOLUCIONADOS and nuevo not in ESTADOS_SOLUCIONADOS:
        eventos.append(REAPERTURA)
    if anterior != ESCALADO and nuevo == ESCALADO:
        eventos.append(ESCALAMIENTO)
    return eventos


@dataclass(frozen=True)
class FechasAproximadas:
    fecha_solucion: datetime | None
    fecha_cierre: datetime | None


def aplicar_eventos(
    actuales: FechasAproximadas, eventos: list[str], fecha: datetime
) -> FechasAproximadas:
    """Actualiza las fechas aproximadas de solución y cierre con los eventos nuevos."""
    solucion, cierre = actuales.fecha_solucion, actuales.fecha_cierre
    for evento in eventos:
        if evento == REAPERTURA:
            solucion, cierre = None, None
        elif evento == SOLUCION:
            solucion = fecha
        elif evento == CIERRE:
            cierre = fecha
            solucion = solucion or fecha
    return FechasAproximadas(solucion, cierre)
