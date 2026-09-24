"""Diálogos de mensajes en español y manejador global de excepciones (RNF-11)."""

import logging
import sys

from PySide6.QtWidgets import QMessageBox, QWidget

from core.errores import MENSAJE_INESPERADO, ErrorAplicacion

log = logging.getLogger(__name__)

TITULO = "Analizador GLPI"


def mostrar_error(mensaje: str, padre: QWidget | None = None) -> None:
    QMessageBox.critical(padre, TITULO, mensaje)


def mostrar_info(mensaje: str, padre: QWidget | None = None) -> None:
    QMessageBox.information(padre, TITULO, mensaje)


def confirmar(mensaje: str, padre: QWidget | None = None) -> bool:
    respuesta = QMessageBox.question(
        padre, TITULO, mensaje,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return respuesta == QMessageBox.StandardButton.Yes


def instalar_manejador_excepciones() -> None:
    """Todo error no controlado va completo al log y al usuario en español."""

    def manejador(tipo, valor, traza):
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, valor, traza)
            return
        if isinstance(valor, ErrorAplicacion):
            log.error(
                "%s | %s", valor.mensaje, valor.detalle, exc_info=(tipo, valor, traza)
            )
            mostrar_error(valor.mensaje)
        else:
            log.critical("Error no controlado", exc_info=(tipo, valor, traza))
            mostrar_error(MENSAJE_INESPERADO)

    sys.excepthook = manejador
