"""PAN-01: inicio de sesión y asistente de primera ejecución.

El asistente crea el coordinador y pide las franjas de turno, la prioridad P1,
los objetivos de SLA y los umbrales de "sin actualizar". Los objetivos de SLA no
se suponen: si el coordinador no los tiene, quedan vacíos y KPI-07 lo indica.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWizard, QWizardPage,
)

from core import config, configuracion, reloj, rutas, seguridad
from core.arranque import Contexto
from core.dominio import PRIORIDADES
from core.errores import ErrorAplicacion, ErrorValidacion
from core.seguridad import Sesion
from core.turnos import interpretar_franja, validar_franjas
from core.version import VERSION
from ui.dialogos import confirmar, mostrar_error

NOMBRE_PERFIL = {seguridad.COORDINADOR: "Coordinador", seguridad.CONSULTA: "Consulta"}


class DialogoInicioSesion(QDialog):
    """Selección de usuario y PIN. Tras varios PIN incorrectos exige esperar."""

    def __init__(self, contexto: Contexto, padre=None):
        super().__init__(padre)
        self.contexto = contexto
        self.sesion: Sesion | None = None
        self.control = seguridad.ControlIntentos()
        self.setWindowTitle(f"Analizador GLPI {VERSION} – Iniciar sesión")
        self.setMinimumWidth(380)

        titulo = QLabel("Analizador GLPI")
        titulo.setObjectName("tituloPantalla")
        self.usuario = QComboBox()
        for fila in seguridad.listar_usuarios_activos(contexto.conexion):
            self.usuario.addItem(f"{fila['nombre']} ({NOMBRE_PERFIL[fila['perfil']]})", fila["id"])
        self.pin = QLineEdit(echoMode=QLineEdit.EchoMode.Password, placeholderText="PIN")
        self.pin.returnPressed.connect(self.entrar)
        self.mensaje = QLabel()
        self.mensaje.setStyleSheet("color: #C62828;")
        self.mensaje.setWordWrap(True)
        self.boton = QPushButton("Entrar")
        self.boton.clicked.connect(self.entrar)
        self.boton.setDefault(True)

        formulario = QFormLayout()
        formulario.addRow("Usuario:", self.usuario)
        formulario.addRow("PIN:", self.pin)
        diseno = QVBoxLayout(self)
        diseno.addWidget(titulo)
        diseno.addLayout(formulario)
        diseno.addWidget(self.mensaje)
        diseno.addWidget(self.boton, alignment=Qt.AlignmentFlag.AlignRight)

        self.reloj_espera = QTimer(self, interval=1000)
        self.reloj_espera.timeout.connect(self._actualizar_espera)

    def entrar(self) -> None:
        if self.control.segundos_restantes(reloj.ahora()):
            return
        try:
            self.sesion = seguridad.iniciar_sesion(
                self.contexto.conexion, self.usuario.currentData(), self.pin.text()
            )
        except ErrorAplicacion as error:
            espera = self.control.registrar_fallo(reloj.ahora())
            self.pin.clear()
            self.mensaje.setText(error.mensaje)
            if espera:
                self._actualizar_espera()
                self.reloj_espera.start()
            return
        self.control.registrar_acierto()
        self.accept()

    def _actualizar_espera(self) -> None:
        restantes = self.control.segundos_restantes(reloj.ahora())
        self.boton.setEnabled(restantes == 0)
        self.pin.setEnabled(restantes == 0)
        if restantes:
            self.mensaje.setText(f"Demasiados intentos. Espere {restantes} s para volver a intentar.")
        else:
            self.reloj_espera.stop()
            self.mensaje.setText("")
            self.pin.setFocus()


# --- Asistente de primera ejecución ---

class PaginaCoordinador(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Coordinador")
        self.setSubTitle("Cree el usuario coordinador. Tendrá acceso a todo y administrará a los demás usuarios.")
        self.nombre = QLineEdit()
        self.pin = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        self.pin2 = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        formulario = QFormLayout(self)
        formulario.addRow("Nombre:", self.nombre)
        formulario.addRow("PIN (4 a 12 dígitos):", self.pin)
        formulario.addRow("Repita el PIN:", self.pin2)

    def validatePage(self) -> bool:
        try:
            if not self.nombre.text().strip():
                raise ErrorValidacion("Escriba el nombre del coordinador.")
            seguridad.validar_pin(self.pin.text())
            if self.pin.text() != self.pin2.text():
                raise ErrorValidacion("Los dos PIN no coinciden.")
        except ErrorValidacion as error:
            mostrar_error(error.mensaje, self)
            return False
        return True


class PaginaTurnos(QWizardPage):
    def __init__(self, contexto: Contexto):
        super().__init__()
        self.setTitle("Franjas de turno")
        self.setSubTitle(
            "Horario de cada turno para clasificar la hora de apertura de los tickets. "
            "No pueden solaparse y deben cubrir las 24 horas. «Día Intermedio» se asigna "
            "a cada técnico en Configuración; no es franja de apertura."
        )
        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Turno", "Franja (HH:MM-HH:MM)"])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for franja in contexto.config.turnos:
            self._agregar(franja.turno, franja.texto)
        agregar = QPushButton("Agregar turno")
        quitar = QPushButton("Quitar turno")
        quitar.setObjectName("secundario")
        agregar.clicked.connect(lambda: self._agregar("", ""))
        quitar.clicked.connect(lambda: self.tabla.removeRow(self.tabla.currentRow()))
        botones = QHBoxLayout()
        botones.addWidget(agregar)
        botones.addWidget(quitar)
        botones.addStretch()
        diseno = QVBoxLayout(self)
        diseno.addWidget(self.tabla)
        diseno.addLayout(botones)

    def _agregar(self, turno: str, franja: str) -> None:
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        self.tabla.setItem(fila, 0, QTableWidgetItem(turno))
        self.tabla.setItem(fila, 1, QTableWidgetItem(franja))

    def franjas(self) -> dict[str, str]:
        resultado = {}
        for fila in range(self.tabla.rowCount()):
            turno = (self.tabla.item(fila, 0) or QTableWidgetItem("")).text().strip()
            franja = (self.tabla.item(fila, 1) or QTableWidgetItem("")).text().strip()
            if turno or franja:
                resultado[turno] = franja
        return resultado

    def validatePage(self) -> bool:
        try:
            franjas = self.franjas()
            if "" in franjas:
                raise ErrorValidacion("Escriba el nombre de cada turno.")
            validar_franjas(tuple(interpretar_franja(t, f) for t, f in franjas.items()))
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return False
        return True


class PaginaPrioridades(QWizardPage):
    def __init__(self, contexto: Contexto):
        super().__init__()
        self.setTitle("Prioridades y SLA")
        self.setSubTitle(
            "Objetivo de resolución en horas por prioridad (KPI-07) y horas sin actualización "
            "a partir de las cuales un ticket abierto se considera desatendido (KPI-16). "
            "Si todavía no tiene un objetivo de SLA, déjelo vacío."
        )
        conexion = contexto.conexion
        self.p1 = QComboBox()
        for p in PRIORIDADES:
            self.p1.addItem(f"{p.nombre} y superiores", p.nivel)
        self.p1.setCurrentIndex(self.p1.findData(int(configuracion.parametro_texto(conexion, "prioridad_p1"))))
        formulario = QFormLayout(self)
        formulario.addRow("Prioridad P1 (crítica):", self.p1)
        self.sla: dict[str, QLineEdit] = {}
        self.sin_actualizar: dict[str, QLineEdit] = {}
        for p in PRIORIDADES:
            sla = QLineEdit(configuracion.parametro_texto(conexion, f"sla_horas_{p.clave}"), placeholderText="sin definir")
            horas = QLineEdit(configuracion.parametro_texto(conexion, f"horas_sin_actualizar_{p.clave}"))
            fila = QHBoxLayout()
            fila.addWidget(QLabel("SLA (h):"))
            fila.addWidget(sla)
            fila.addWidget(QLabel("Sin actualizar después de (h):"))
            fila.addWidget(horas)
            formulario.addRow(f"{p.nombre}:", fila)
            self.sla[p.clave] = sla
            self.sin_actualizar[p.clave] = horas

    def validatePage(self) -> bool:
        for p in PRIORIDADES:
            for campo, texto in (("SLA", self.sla[p.clave].text()), ("sin actualizar", self.sin_actualizar[p.clave].text())):
                texto = texto.strip().replace(",", ".")
                if campo == "sin actualizar" and not texto:
                    mostrar_error(f"Indique las horas «sin actualizar» de la prioridad {p.nombre}.", self)
                    return False
                if texto:
                    try:
                        if float(texto) < 0:
                            raise ValueError
                    except ValueError:
                        mostrar_error(f"El valor {campo} de la prioridad {p.nombre} debe ser un número positivo.", self)
                        return False
        vacios = [p.nombre for p in PRIORIDADES if not self.sla[p.clave].text().strip()]
        if vacios:
            return confirmar(
                "No definió el objetivo de SLA para: " + ", ".join(vacios)
                + ".\nEl cumplimiento SLA (KPI-07) no se calculará para esas prioridades "
                "hasta que lo defina en Configuración. ¿Continuar?",
                self,
            )
        return True


class AsistenteConfiguracion(QWizard):
    """Primera ejecución: al terminar deja creado el coordinador y su sesión iniciada."""

    def __init__(self, contexto: Contexto, padre=None):
        super().__init__(padre)
        self.contexto = contexto
        self.sesion: Sesion | None = None
        self.setWindowTitle("Analizador GLPI – Configuración inicial")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(720, 520)
        self.setButtonText(QWizard.WizardButton.NextButton, "Siguiente >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Atrás")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Terminar")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Cancelar")
        self.coordinador = PaginaCoordinador()
        self.turnos = PaginaTurnos(contexto)
        self.prioridades = PaginaPrioridades(contexto)
        for pagina in (self.coordinador, self.turnos, self.prioridades):
            self.addPage(pagina)

    def accept(self) -> None:
        conexion = self.contexto.conexion
        try:
            if self.sesion is None:  # si un paso posterior falló, el coordinador ya existe
                usuario_id = seguridad.crear_usuario(
                    conexion, None, nombre=self.coordinador.nombre.text(),
                    perfil=seguridad.COORDINADOR, pin=self.coordinador.pin.text(),
                )
                self.sesion = seguridad.iniciar_sesion(conexion, usuario_id, self.coordinador.pin.text())
            configuracion.guardar_franjas(conexion, self.sesion, self.contexto.config.archivo, self.turnos.franjas())
            self.contexto.config = config.cargar(self.contexto.config.archivo, rutas.directorio_base())
            configuracion.actualizar_parametro(conexion, self.sesion, "prioridad_p1", str(self.prioridades.p1.currentData()))
            for p in PRIORIDADES:
                configuracion.actualizar_parametro(conexion, self.sesion, f"sla_horas_{p.clave}", self.prioridades.sla[p.clave].text())
                configuracion.actualizar_parametro(
                    conexion, self.sesion, f"horas_sin_actualizar_{p.clave}", self.prioridades.sin_actualizar[p.clave].text()
                )
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        super().accept()
