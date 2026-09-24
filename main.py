"""Punto de entrada del Analizador GLPI."""

import logging
import sys

from PySide6.QtWidgets import QApplication

from core.arranque import arrancar
from core.errores import MENSAJE_INESPERADO, ErrorAplicacion
from ui.dialogos import instalar_manejador_excepciones, mostrar_error
from ui.ventana_principal import VentanaPrincipal

log = logging.getLogger(__name__)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Analizador GLPI")
    instalar_manejador_excepciones()
    try:
        contexto = arrancar()
    except ErrorAplicacion as error:
        log.error("Arranque fallido: %s | %s", error.mensaje, error.detalle)
        mostrar_error(error.mensaje)
        return 1
    except Exception:
        log.critical("Arranque fallido por un error no controlado", exc_info=True)
        mostrar_error(MENSAJE_INESPERADO)
        return 1
    try:
        ventana = VentanaPrincipal(contexto)
        ventana.show()
        return app.exec()
    finally:
        contexto.conexion.close()


if __name__ == "__main__":
    sys.exit(main())
