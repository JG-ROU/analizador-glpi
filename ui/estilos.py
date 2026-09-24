"""Carga del estilo QSS corporativo incluido en assets/ (RNF-02: sin internet)."""

import logging

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from core import rutas

log = logging.getLogger(__name__)

ARCHIVO_QSS = "assets/estilos/principal.qss"
# Segoe UI no trae ✔ ✖ ⚠: se toman de Segoe UI Symbol (incluida en Windows 10/11)
FUENTES = ["Segoe UI", "Segoe UI Symbol"]


def aplicar(app: QApplication) -> None:
    fuente = QFont()
    fuente.setFamilies(FUENTES)
    fuente.setPointSize(10)
    app.setFont(fuente)
    ruta = rutas.directorio_recursos() / ARCHIVO_QSS
    try:
        app.setStyleSheet(ruta.read_text(encoding="utf-8"))
    except OSError:
        # Sin estilo la aplicación sigue funcionando con el aspecto del sistema
        log.warning("No se encontró la hoja de estilos %s", ruta)
