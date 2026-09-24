"""Casilla tri-estado para los criterios de calidad (CAL-01): ✔ cumple, ✖ no cumple, — no aplica.

Cada clic pasa al estado siguiente. El estado siempre se muestra con símbolo y texto
(RNF-12), no solo con color.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton

from core.analisis.calidad import CUMPLE, NO_APLICA, NO_CUMPLE

ORDEN = (CUMPLE, NO_CUMPLE, NO_APLICA)
TEXTO = {CUMPLE: "✔ Cumple", NO_CUMPLE: "✖ No cumple", NO_APLICA: "— No aplica", None: "Sin marcar"}
ESTILO = {
    CUMPLE: "background: #E8F5E9; color: #1B5E20; border: 1px solid #2E7D32;",
    NO_CUMPLE: "background: #FFEBEE; color: #B71C1C; border: 1px solid #C62828;",
    NO_APLICA: "background: #ECEFF1; color: #455A64; border: 1px solid #90A4AE;",
    None: "background: #FFFFFF; color: #5A6B7B; border: 1px dashed #90A4AE;",
}


class CasillaTriEstado(QPushButton):
    cambiado = Signal(object)

    def __init__(self, valor: str | None = None, padre=None):
        super().__init__(padre)
        self.setMinimumWidth(120)
        self.valor = None
        self.fijar(valor)
        self.clicked.connect(self._siguiente)

    def fijar(self, valor: str | None) -> None:
        self.valor = valor
        self.setText(TEXTO[valor])
        self.setStyleSheet(f"QPushButton {{ {ESTILO[valor]} border-radius: 4px; padding: 4px 8px; }}")
        self.cambiado.emit(valor)

    def _siguiente(self) -> None:
        indice = ORDEN.index(self.valor) + 1 if self.valor in ORDEN else 0
        self.fijar(ORDEN[indice % len(ORDEN)])
