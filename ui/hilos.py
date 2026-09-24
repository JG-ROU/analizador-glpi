"""Tareas largas en hilos de trabajo (RNF-06): la interfaz nunca se congela.

Cada tarea abre su propia conexión a la BD, porque sqlite3 no comparte una
conexión entre hilos.
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal

from core.errores import MENSAJE_INESPERADO, ErrorAplicacion

log = logging.getLogger(__name__)

Avance = Callable[[int, int], None]


class Trabajo(QThread):
    avance = Signal(int, int)
    listo = Signal(object)
    fallo = Signal(str)

    def __init__(self, funcion: Callable[[Avance], object], padre: QObject | None = None):
        super().__init__(padre)
        self.funcion = funcion

    def run(self) -> None:
        try:
            resultado = self.funcion(lambda hechas, total: self.avance.emit(hechas, total))
        except ErrorAplicacion as error:
            log.error("%s | %s", error.mensaje, error.detalle, exc_info=True)
            self.fallo.emit(error.mensaje)
        except Exception:
            log.critical("Error no controlado en una tarea en segundo plano", exc_info=True)
            self.fallo.emit(MENSAJE_INESPERADO)
        else:
            self.listo.emit(resultado)


def ejecutar(
    padre: QObject,
    funcion: Callable[[Avance], object],
    al_terminar: Callable[[object], None],
    al_fallar: Callable[[str], None],
    al_avanzar: Callable[[int, int], None] | None = None,
) -> Trabajo:
    """Lanza la tarea y mantiene la referencia hasta que termine."""
    trabajo = Trabajo(funcion, padre)
    trabajo.listo.connect(al_terminar)
    trabajo.fallo.connect(al_fallar)
    if al_avanzar:
        trabajo.avance.connect(al_avanzar)
    pendientes = padre.__dict__.setdefault("_trabajos", [])
    pendientes.append(trabajo)
    trabajo.finished.connect(lambda: pendientes.remove(trabajo) if trabajo in pendientes else None)
    trabajo.start()
    return trabajo


def con_conexion(estado, funcion: Callable) -> Callable[[Avance], object]:
    """Envuelve `funcion(conexion, avance)` para que use una conexión propia del hilo."""
    def envoltura(avance: Avance):
        conexion = estado.nueva_conexion()
        try:
            return funcion(conexion, avance)
        finally:
            conexion.close()
    return envoltura
