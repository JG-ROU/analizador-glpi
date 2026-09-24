"""Ventana principal: menú lateral, barra superior con período, turno, última
importación y alertas, y las pantallas de la Fase 1 (spec 06)."""

from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

import logging

from core import parametros, reloj
from core import notificaciones
from core.analisis import hallazgos
from core.importacion import carga
from ui.hilos import con_conexion, ejecutar
from ui.pantallas.hallazgos import PantallaHallazgos
from core.version import VERSION
from ui.componentes.selector_periodo import SelectorPeriodo
from ui.estado import EstadoApp
from ui.pantallas.calidad import PantallaCalidad
from ui.pantallas.clasificacion import PantallaClasificacion
from ui.pantallas.configuracion import PantallaConfiguracion
from ui.pantallas.dashboard import PantallaDashboard
from ui.pantallas.estaciones import PantallaEstaciones
from ui.pantallas.tipificaciones import PantallaTipificaciones
from ui.pantallas.historial import PantallaHistorial
from ui.pantallas.importar import PantallaImportar
from ui.pantallas.kpis import PantallaKPIs
from ui.pantallas.novedades import PantallaNovedades
from ui.pantallas.reportes import PantallaReportes
from ui.pantallas.responsables import PantallaResponsables

TODOS_LOS_TURNOS = "Todos los turnos"
log = logging.getLogger(__name__)


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
            clases += [PantallaImportar, PantallaClasificacion, PantallaNovedades, PantallaHallazgos,
                       PantallaEstaciones, PantallaTipificaciones, PantallaResponsables, PantallaCalidad,
                       PantallaReportes, PantallaKPIs, PantallaConfiguracion, PantallaHistorial]
        elif sesion.tecnico_id is not None:
            clases += [PantallaNovedades, PantallaEstaciones, PantallaTipificaciones, PantallaResponsables,
                       PantallaCalidad, PantallaReportes]
        else:
            clases += [PantallaEstaciones, PantallaTipificaciones, PantallaReportes]
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
        derecha.addWidget(self._barra_avisos())
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
        self._actualizar_campana()
        # Hallazgos al iniciar (spec 08), en segundo plano
        ejecutar(self, con_conexion(estado, lambda conexion, avance: hallazgos.detectar(conexion)),
                 lambda resumen: estado.datos_cambiados.emit(),
                 lambda mensaje: log.warning("No se pudieron detectar hallazgos al iniciar: %s", mensaje))

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
        campana.clicked.connect(self._ir_a_hallazgos)
        self.campana = campana
        usuario = QLabel(f"👤 {self.estado.sesion.nombre}")
        acerca = QPushButton("Acerca de")
        acerca.setObjectName("secundario")
        acerca.clicked.connect(self._acerca_de)
        diseno.addWidget(self.titulo)
        diseno.addStretch()
        for widget in (self.selector, QLabel("Turno:"), self.turno, self.importacion, campana, usuario, acerca):
            diseno.addWidget(widget)
        return barra

    def _barra_avisos(self) -> QFrame:
        """Notificaciones al iniciar (NOT-01, NOT-02, NOT-03), con acceso a la pantalla sugerida."""
        self.avisos = QFrame(objectName="barraAvisos")
        diseno = QHBoxLayout(self.avisos)
        diseno.setContentsMargins(12, 6, 12, 6)
        self.texto_avisos = QLabel(objectName="aviso")
        self.texto_avisos.setWordWrap(True)
        self.boton_aviso = QPushButton()
        self.boton_aviso.setObjectName("secundario")
        self.boton_aviso.clicked.connect(lambda: self.ir_a(self._destino_aviso))
        cerrar = QToolButton(text="✕")
        cerrar.setToolTip("Ocultar avisos")
        cerrar.clicked.connect(self.avisos.hide)
        diseno.addWidget(self.texto_avisos, 1)
        diseno.addWidget(self.boton_aviso)
        diseno.addWidget(cerrar)
        self.mostrar_notificaciones(notificaciones.pendientes(
            self.estado.conexion, self.estado.sesion, notificaciones.AL_INICIAR))
        return self.avisos

    def mostrar_notificaciones(self, lista: list) -> None:
        self.avisos.setVisible(bool(lista))
        self.texto_avisos.setText("\n".join(f"{n.codigo} · {n.mensaje}" for n in lista))
        self._destino_aviso = next((n.accion for n in lista if n.accion), None)
        self.boton_aviso.setVisible(self._destino_aviso is not None)
        if self._destino_aviso:
            self.boton_aviso.setText(f"Ir a {self._destino_aviso}")

    def ir_a(self, titulo: str) -> None:
        for indice, pantalla in enumerate(self.pantallas):
            if pantalla.titulo == titulo:
                self.menu.setCurrentRow(indice)
                return

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
        self._actualizar_campana()
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

    def _actualizar_campana(self) -> None:
        conteo = hallazgos.conteo_nuevos(self.estado.conexion, self.estado.sesion)
        self.campana.setText(f"🔔 {conteo['ALTA']}" if conteo["ALTA"] else "🔔")
        self.campana.setToolTip(
            f"Hallazgos nuevos: {conteo['ALTA']} de severidad alta, {conteo['MEDIA']} media, {conteo['BAJA']} baja."
        )

    def _ir_a_hallazgos(self) -> None:
        for indice, pantalla in enumerate(self.pantallas):
            if isinstance(pantalla, PantallaHallazgos):
                self.menu.setCurrentRow(indice)
                return
        self.menu.setCurrentRow(0)  # la consulta ve los hallazgos en el panel del dashboard

    def _acerca_de(self) -> None:
        QMessageBox.about(
            self, "Acerca de",
            f"<b>Analizador GLPI</b><br>Versión {VERSION}<br><br>"
            "Indicadores, SLA y calidad de soporte a partir de las exportaciones de GLPI 9.1.4.<br>"
            "Funciona sin conexión; los datos se guardan solo en este equipo.",
        )

    def closeEvent(self, evento) -> None:
        for pantalla in [self, *self.pantallas]:
            for trabajo in list(pantalla.__dict__.get("_trabajos", [])):
                trabajo.wait(5000)
        super().closeEvent(evento)
