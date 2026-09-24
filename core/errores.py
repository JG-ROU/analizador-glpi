"""Errores de la aplicación con mensaje en español para el usuario (RNF-11).

El mensaje se muestra en pantalla; el detalle técnico solo va a logs/app.log.
"""

MENSAJE_INESPERADO = (
    "Ocurrió un error inesperado. El detalle quedó registrado en logs/app.log."
)


class ErrorAplicacion(Exception):
    """Error previsto: `mensaje` es para el usuario y `detalle` para el log."""

    def __init__(self, mensaje: str, detalle: str | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle


class ErrorConfiguracion(ErrorAplicacion):
    """config.ini falta, está mal formado o tiene valores inválidos."""


class ErrorValidacion(ErrorAplicacion):
    """Un dato ingresado por el usuario no es válido."""


class ErrorAutenticacion(ErrorAplicacion):
    """Usuario inexistente, inactivo o PIN incorrecto."""


class ErrorPermiso(ErrorAplicacion):
    """El perfil de la sesión no permite la operación (RNF-07)."""
