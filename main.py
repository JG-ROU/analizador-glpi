"""Punto de entrada del Analizador GLPI.

Arranque: config.ini, carpetas, logs, BD con migraciones y respaldo diario. Luego,
en la primera ejecución, el asistente de configuración; si no, el inicio de sesión.
"""

import logging
import sys

from PySide6.QtWidgets import QApplication, QDialog

from core import seguridad
from core.arranque import arrancar
from core.errores import MENSAJE_INESPERADO, ErrorAplicacion
from ui import estilos
from ui.dialogos import instalar_manejador_excepciones, mostrar_error
from ui.estado import EstadoApp
from ui.pantallas.inicio_sesion import AsistenteConfiguracion, DialogoInicioSesion
from ui.ventana_principal import VentanaPrincipal

log = logging.getLogger(__name__)


def iniciar_sesion(contexto):
    """Asistente en la primera ejecución; si no, selección de usuario y PIN."""
    if not seguridad.hay_usuarios(contexto.conexion):
        asistente = AsistenteConfiguracion(contexto)
        return asistente.sesion if asistente.exec() == QDialog.DialogCode.Accepted else None
    dialogo = DialogoInicioSesion(contexto)
    return dialogo.sesion if dialogo.exec() == QDialog.DialogCode.Accepted else None


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Analizador GLPI")
    estilos.aplicar(app)
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
        sesion = iniciar_sesion(contexto)
        if sesion is None:
            return 0
        log.info("Sesión iniciada: %s (%s)", sesion.nombre, sesion.perfil)
        ventana = VentanaPrincipal(EstadoApp(contexto, sesion))
        ventana.show()
        return app.exec()
    finally:
        contexto.conexion.close()


if __name__ == "__main__":
    sys.exit(main())
