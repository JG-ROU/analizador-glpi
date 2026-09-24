"""Gráfico de matplotlib embebido (FigureCanvasQTAgg). Las figuras vienen de core/reportes."""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget


class Grafico(QWidget):
    def __init__(self, padre=None):
        super().__init__(padre)
        self._diseno = QVBoxLayout(self)
        self._diseno.setContentsMargins(0, 0, 0, 0)
        self._lienzo: FigureCanvasQTAgg | None = None
        self.setMinimumHeight(240)

    def mostrar(self, figura: Figure) -> None:
        if self._lienzo is not None:
            self._diseno.removeWidget(self._lienzo)
            self._lienzo.deleteLater()
        self._lienzo = FigureCanvasQTAgg(figura)
        self._lienzo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._diseno.addWidget(self._lienzo)
        self._lienzo.draw_idle()
