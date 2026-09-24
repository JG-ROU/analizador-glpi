"""Ventana principal: menú lateral, barra superior con período, turno, última
importación y alertas, y las pantallas de la Fase 1 (spec 06)."""

from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from core import parametros, reloj
from core.importacion import carga
from core.version import VERSION
from ui.componentes.selector_periodo import SelectorPeriodo
from ui.estado import EstadoApp
from ui.pantallas.clasificacion import PantallaClasificacion
from ui.pantallas.configuracion import PantallaConfiguracion
from ui.pantallas.dashboard import PantallaDashboard
from ui.pantallas.historial import PantallaHistorial
from ui.pantallas.importar import PantallaImportar
from ui.pantallas.kpis import PantallaKPIs
from ui.pantallas.novedades import PantallaNovedades
from ui.pantallas.responsables import PantallaResponsables

TODOS_LOS_TURNOS = "Todos los turnos"


class VentanaPrincipal(QMainWindow):
    def __init__(self, estado: EstadoApp):
        super().__init__()
        self.estado = estado
        sesion = estado.sesion
        self.setWindowTitle(f"Analizador GLPI {VERSION} – {sesion.nombre}")
        self.resize(1360, 860)

        # Pantallas según el perfil; los permisos también se aplican en core/
        clases = [PantallaDashboard]
        if sesion.es_coordinador:
            clases += [PantallaImportar, PantallaClasificacion, PantallaNovedades, PantallaResponsables,
                       PantallaKPIs, PantallaConfiguracion, PantallaHistorial]
        elif sesion.tecnico_id is not None:
            clases += [PantallaNovedades, PantallaResponsables]
        self.pantallas = [clase(estado) for clase in clases]
        self._pendientes = set(range(len(self.pantallas)))

        self.menu = QListWidget(objectName="menuLateral")
        self.menu.setFixedWidth(200)
        self.pila = QStackedWidget()
        for pantalla in self.pantallas:
            self.menu.addItem(pantalla.titulo)
            self.pila.addWidget(pantalla)
        self.menu.currentRowChanged.connect(self._mostrar)

        central = QWidget()
        cuerpo = QHBoxLayout(central)
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(0)
        cuerpo.addWidget(self.menu)
        derecha = QVBoxLayout()
        derecha.setContentsMargins(0, 0, 0, 0)
        derecha.addWidget(self._barra_superior())
        contenedor = QWidget()
        diseno_pila = QVBoxLayout(contenedor)
        diseno_pila.addWidget(self.pila)
        derecha.addWidget(contenedor, 1)
        cuerpo.addLayout(derecha, 1)
        self.setCentralWidget(central)

        estado.cambio_filtros.connect(self._invalidar)
        estado.datos_cambiados.connect(self._datos_cambiados)
        self.menu.setCurrentRow(0)
        self._actualizar_importacion()

    def _barra_superior(self) -> QFrame:
        barra = QFrame(objectName="barraSuperior")
        diseno = QHBoxLayout(barra)
        self.titulo = QLabel(objectName="tituloPantalla")
        self.selector = SelectorPeriodo(self.estado.periodo)
        self.selector.cambiado.connect(self.estado.fijar_periodo)
        self.turno = QComboBox()
        self._cargar_turnos()
        self.turno.activated.connect(
            lambda: self.estado.fijar_turno(None if self.turno.currentText() == TODOS_LOS_TURNOS else self.turno.currentText())
        )
        self.importacion = QLabel()
        campana = QToolButton(text="🔔")
        campana.setEnabled(False)
        campana.setToolTip("Las alertas (notificaciones NOT-xx) se incorporan en la Fase 2.")
        usuario = QLabel(f"👤 {self.estado.sesion.nombre}")
        acerca = QPushButton("Acerca de")
        acerca.setObjectName("secundario")
        acerca.clicked.connect(self._acerca_de)
        diseno.addWidget(self.titulo)
        diseno.addStretch()
        for widget in (self.selector, QLabel("Turno:"), self.turno, self.importacion, campana, usuario, acerca):
            diseno.addWidget(widget)
        return barra

    def _cargar_turnos(self) -> None:
        self.turno.clear()
        self.turno.addItem(TODOS_LOS_TURNOS)
        self.turno.addItems([f.turno for f in self.estado.config.turnos])

    # --- Navegación y refresco ---

    def _mostrar(self, indice: int) -> None:
        if indice < 0:
            return
        self.pila.setCurrentIndex(indice)
        self.titulo.setText(self.pantallas[indice].titulo)
        if indice in self._pendientes:
            self._pendientes.discard(indice)
            self.pantallas[indice].actualizar()

    def _invalidar(self) -> None:
        """Marca todas las pantallas para refrescar; la visible se refresca ya."""
        self._pendientes = set(range(len(self.pantallas)))
        self._mostrar(self.pila.currentIndex())

    def _datos_cambiados(self) -> None:
        self._cargar_turnos()
        self._actualizar_importacion()
        self._pendientes = set(range(len(self.pantallas))) - {self.pila.currentIndex()}

    def _actualizar_importacion(self) -> None:
        """Fecha de la última importación, en rojo si supera el umbral (NOT-01)."""
        ultima = carga.ultima_importacion(self.estado.conexion)
        if ultima is None:
            self.importacion.setText("Sin importaciones")
            self.importacion.setObjectName("importacionVencida")
        else:
            dias = parametros.entero(self.estado.conexion, "dias_importacion_desactualizada")
            vencida = (reloj.ahora() - ultima).days >= dias
            self.importacion.setText(f"Última importación: {ultima:%d/%m %H:%M}")
            self.importacion.setObjectName("importacionVencida" if vencida else "")
            self.importacion.setToolTip(
                f"Hace más de {dias} día(s): importe una exportación reciente de GLPI." if vencida else ""
            )
        self.importacion.style().unpolish(self.importacion)
        self.importacion.style().polish(self.importacion)

    def _acerca_de(self) -> None:
        QMessageBox.about(
            self, "Acerca de",
            f"<b>Analizador GLPI</b><br>Versión {VERSION}<br><br>"
            "Indicadores, SLA y calidad de soporte a partir de las exportaciones de GLPI 9.1.4.<br>"
            "Funciona sin conexión; los datos se guardan solo en este equipo.",
        )

    def closeEvent(self, evento) -> None:
        for pantalla in self.pantallas:
            for trabajo in list(pantalla.__dict__.get("_trabajos", [])):
                trabajo.wait(5000)
        super().closeEvent(evento)
