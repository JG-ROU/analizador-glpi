"""Estadísticas de los indicadores (RN-02, RN-03, RN-04).

Los tiempos se resumen con la mediana y el P90, porque unos pocos casos largos
distorsionan el promedio. El P90 usa interpolación lineal, igual que
PERCENTIL.INC de Excel, para que el coordinador pueda verificarlo a mano.
"""

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

AVISO_SIN_ESPERA = "Tiempos sin descontar espera"
AVISO_MUESTRA_PEQUENA = "⚠ muestra pequeña"
DECIMALES = 2


@dataclass(frozen=True)
class ResumenTiempos:
    cantidad: int
    mediana: float | None
    p90: float | None
    promedio: float | None
    muestra_pequena: bool


def _limpios(valores: Iterable[float | None]) -> np.ndarray:
    datos = np.array([v for v in valores if v is not None], dtype=float)
    return datos[~np.isnan(datos)]


def _redondear(valor: float) -> float:
    return round(float(valor), DECIMALES)


def mediana(valores: Iterable[float | None]) -> float | None:
    datos = _limpios(valores)
    return _redondear(np.median(datos)) if datos.size else None


def percentil(valores: Iterable[float | None], p: float) -> float | None:
    datos = _limpios(valores)
    return _redondear(np.percentile(datos, p)) if datos.size else None


def promedio(valores: Iterable[float | None]) -> float | None:
    datos = _limpios(valores)
    return _redondear(datos.mean()) if datos.size else None


def muestra_pequena(cantidad: int, muestra_minima: int) -> bool:
    """RN-04: menos de `muestra_minima` tickets → aviso y fuera de rankings."""
    return cantidad < muestra_minima


def resumir_tiempos(valores: Iterable[float | None], muestra_minima: int) -> ResumenTiempos:
    datos = _limpios(valores)
    return ResumenTiempos(
        cantidad=int(datos.size),
        mediana=mediana(datos),
        p90=percentil(datos, 90),
        promedio=promedio(datos),
        muestra_pequena=muestra_pequena(int(datos.size), muestra_minima),
    )


def porcentaje(numerador: float, denominador: float) -> float | None:
    """numerador / denominador × 100; None si no hay denominador."""
    if not denominador:
        return None
    return _redondear(numerador / denominador * 100)
