"""Estado compartido de la interfaz: contexto, sesión, período y filtros globales."""

import sqlite3

from PySide6.QtCore import QObject, Signal

from core import config as config_core
from core import reloj, rutas
from core.analisis import periodos
from core.analisis.filtros import Filtros
from core.arranque import Contexto
from core.db import conexion as conexion_db
from core.seguridad import Sesion


class EstadoApp(QObject):
    """Las pantallas escuchan `cambio_filtros` (período o turno) y `datos_cambiados`
    (importación, restauración o cambio de configuración) para refrescarse."""

    cambio_filtros = Signal()
    datos_cambiados = Signal()

    def __init__(self, contexto: Contexto, sesion: Sesion):
        super().__init__()
        self.contexto = contexto
        self.sesion = sesion
        self.periodo = periodos.mes_de(reloj.ahora())
        self.turno: str | None = None

    @property
    def conexion(self) -> sqlite3.Connection:
        return self.contexto.conexion

    @property
    def config(self) -> config_core.Config:
        return self.contexto.config

    @property
    def filtros(self) -> Filtros:
        return Filtros(turno=self.turno)

    def nueva_conexion(self) -> sqlite3.Connection:
        """Conexión propia para un hilo de trabajo (sqlite3 no comparte conexiones entre hilos)."""
        return conexion_db.conectar(self.config.rutas.base_datos)

    def fijar_periodo(self, periodo: periodos.Periodo) -> None:
        if periodo != self.periodo:
            self.periodo = periodo
            self.cambio_filtros.emit()

    def fijar_turno(self, turno: str | None) -> None:
        if turno != self.turno:
            self.turno = turno
            self.cambio_filtros.emit()

    def recargar_config(self) -> None:
        """Vuelve a leer config.ini (por ejemplo, tras cambiar las franjas de turno)."""
        self.contexto.config = config_core.cargar(self.config.archivo, rutas.directorio_base())
        self.datos_cambiados.emit()
