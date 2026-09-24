"""Ventana principal. Por ahora es provisional; el menú y las pantallas llegan en T15."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow

from core.arranque import Contexto
from core.version import VERSION


class VentanaPrincipal(QMainWindow):
    def __init__(self, contexto: Contexto):
        super().__init__()
        self.contexto = contexto
        self.setWindowTitle(f"Analizador GLPI {VERSION}")
        self.resize(1200, 760)
        aviso = QLabel("Analizador GLPI en construcción.")
        aviso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(aviso)
