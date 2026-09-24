"""Semáforo de los KPIs y criticidad global (spec 05, RNF-12).

El color siempre va acompañado de ícono y texto.
"""

from collections.abc import Iterable

VERDE = "VERDE"
AMARILLO = "AMARILLO"
ROJO = "ROJO"
INFORMATIVO = "INFORMATIVO"
SIN_DATOS = "SIN_DATOS"

MAYOR_MEJOR = "MAYOR_MEJOR"
MENOR_MEJOR = "MENOR_MEJOR"

ICONOS = {VERDE: "✔", AMARILLO: "▲", ROJO: "✖", INFORMATIVO: "ℹ", SIN_DATOS: "—"}
TEXTOS = {
    VERDE: "Verde",
    AMARILLO: "Amarillo",
    ROJO: "Rojo",
    INFORMATIVO: "Informativo",
    SIN_DATOS: "Sin datos",
}
_GRAVEDAD = {VERDE: 1, AMARILLO: 2, ROJO: 3}


def evaluar(
    valor: float | None,
    direccion: str,
    umbral_verde: float | None,
    umbral_amarillo: float | None,
) -> str:
    """Color del valor según la dirección y los umbrales.

    - Mayor es mejor: ≥ verde → verde; ≥ amarillo → amarillo; si no, rojo.
    - Menor es mejor: ≤ verde → verde; ≤ amarillo → amarillo; si no, rojo.
    Sin umbral amarillo solo hay verde o rojo. Sin umbral verde, es informativo.
    """
    if valor is None:
        return SIN_DATOS
    if direccion not in (MAYOR_MEJOR, MENOR_MEJOR) or umbral_verde is None:
        return INFORMATIVO
    if direccion == MAYOR_MEJOR:
        if valor >= umbral_verde:
            return VERDE
        if umbral_amarillo is not None and valor >= umbral_amarillo:
            return AMARILLO
        return ROJO
    if valor <= umbral_verde:
        return VERDE
    if umbral_amarillo is not None and valor <= umbral_amarillo:
        return AMARILLO
    return ROJO


def peor(colores: Iterable[str]) -> str:
    """El color más grave; ignora informativos y sin datos."""
    evaluados = [c for c in colores if c in _GRAVEDAD]
    if not evaluados:
        return SIN_DATOS
    return max(evaluados, key=_GRAVEDAD.get)


def etiqueta(color: str) -> str:
    """Ícono y texto, por ejemplo «✖ Rojo»."""
    return f"{ICONOS[color]} {TEXTOS[color]}"
