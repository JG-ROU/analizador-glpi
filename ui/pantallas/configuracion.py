"""PAN-13: Configuración (solo coordinador). Cada cambio queda en el historial.

Pestañas: parámetros, franjas de turno, técnicos, estaciones, festivos, usuarios,
respaldos y perfiles de importación.
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import clasificacion
from core import configuracion as cfg
from core import reloj, seguridad
from core.db import respaldo
from core.dominio import TURNOS_TECNICO
from core.errores import ErrorAplicacion
from core.importacion import mapeo
from core.importacion.validacion import formato_legible
from ui.dialogos import confirmar, mostrar_error, mostrar_info

NOMBRE_PERFIL = {seguridad.COORDINADOR: "Coordinador", seguridad.CONSULTA: "Consulta"}


def _tabla(encabezados: list[str]) -> QTableWidget:
    tabla = QTableWidget(0, len(encabezados))
    tabla.setHorizontalHeaderLabels(encabezados)
    tabla.verticalHeader().setVisible(False)
    tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    tabla.horizontalHeader().setStretchLastSection(True)
    return tabla


def _celda(texto, editable: bool = False) -> QTableWidgetItem:
    celda = QTableWidgetItem("" if texto is None else str(texto))
    if not editable:
        celda.setFlags(celda.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return celda


def _casilla(marcada: bool) -> QTableWidgetItem:
    celda = QTableWidgetItem()
    celda.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
    celda.setCheckState(Qt.CheckState.Checked if marcada else Qt.CheckState.Unchecked)
    return celda


def _marcada(tabla: QTableWidget, fila: int, columna: int) -> bool:
    return tabla.item(fila, columna).checkState() == Qt.CheckState.Checked


def _botonera(*botones: QPushButton) -> QHBoxLayout:
    fila = QHBoxLayout()
    for boton in botones:
        fila.addWidget(boton)
    fila.addStretch()
    return fila


class PantallaConfiguracion(QWidget):
    titulo = "Configuración"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.pestanas = QTabWidget()
        for titulo, crear in (
            ("Parámetros", self._crear_parametros), ("Turnos", self._crear_turnos),
            ("Técnicos", self._crear_tecnicos), ("Estaciones", self._crear_estaciones),
            ("Festivos", self._crear_festivos), ("Usuarios", self._crear_usuarios),
            ("Respaldos", self._crear_respaldos), ("Perfiles de importación", self._crear_perfiles),
        ):
            self.pestanas.addTab(crear(), titulo)
        QVBoxLayout(self).addWidget(self.pestanas)

    @property
    def conexion(self):
        return self.estado.conexion

    @property
    def sesion(self):
        return self.estado.sesion

    def actualizar(self) -> None:
        for cargar in (self._cargar_parametros, self._cargar_turnos, self._cargar_tecnicos,
                       self._cargar_estaciones, self._cargar_festivos, self._cargar_usuarios, self._cargar_respaldos, self._cargar_perfiles):
            cargar()

    def _guardado(self, errores: list[str], cambios: bool = True) -> None:
        if errores:
            mostrar_error("Algunos cambios no se guardaron:\n- " + "\n- ".join(errores), self)
        elif cambios:
            mostrar_info("Cambios guardados. Quedaron registrados en el historial.", self)
        self.estado.datos_cambiados.emit()
        self.actualizar()

    # --- Parámetros ---

    def _crear_parametros(self) -> QWidget:
        self.parametros = _tabla(["Grupo", "Parámetro", "Descripción", "Valor"])
        self.parametros.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        guardar = QPushButton("Guardar cambios")
        guardar.clicked.connect(self._guardar_parametros)
        pagina = QWidget()
        diseno = QVBoxLayout(pagina)
        nota = QLabel("Los objetivos de SLA y los umbrales de tiempo de resolución pueden quedar vacíos hasta que los defina.")
        nota.setObjectName("nota")
        diseno.addWidget(nota)
        diseno.addWidget(self.parametros)
        diseno.addLayout(_botonera(guardar))
        return pagina

    def _cargar_parametros(self) -> None:
        filas = cfg.listar_parametros(self.conexion)
        self.parametros.setRowCount(len(filas))
        self._parametros_originales = {}
        for i, fila in enumerate(filas):
            self.parametros.setItem(i, 0, _celda(fila["grupo"]))
            self.parametros.setItem(i, 1, _celda(fila["clave"]))
            descripcion = _celda(fila["descripcion"])
            descripcion.setToolTip(fila["descripcion"])
            self.parametros.setItem(i, 2, descripcion)
            self.parametros.setItem(i, 3, _celda(fila["valor"], editable=True))
            self._parametros_originales[fila["clave"]] = fila["valor"] or ""

    def _guardar_parametros(self) -> None:
        errores = []
        for i in range(self.parametros.rowCount()):
            clave = self.parametros.item(i, 1).text()
            texto = self.parametros.item(i, 3).text()
            if texto.strip() == self._parametros_originales.get(clave, ""):
                continue
            try:
                cfg.actualizar_parametro(self.conexion, self.sesion, clave, texto)
            except ErrorAplicacion as error:
                errores.append(error.mensaje)
        self._guardado(errores)

    # --- Turnos ---

    def _crear_turnos(self) -> QWidget:
        self.turnos = _tabla(["Turno", "Franja (HH:MM-HH:MM)"])
        agregar = QPushButton("Agregar turno")
        quitar = QPushButton("Quitar turno")
        quitar.setObjectName("secundario")
        guardar = QPushButton("Guardar franjas")
        agregar.clicked.connect(lambda: self._fila_turno("", ""))
        quitar.clicked.connect(lambda: self.turnos.removeRow(self.turnos.currentRow()))
        guardar.clicked.connect(self._guardar_turnos)
        pagina = QWidget()
        diseno = QVBoxLayout(pagina)
        nota = QLabel("Franjas para el turno de apertura de los tickets: sin solapes y cubriendo las 24 horas. "
                      "Al guardar se actualiza config.ini y se recalcula el turno de los tickets existentes.")
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        diseno.addWidget(nota)
        diseno.addWidget(self.turnos)
        diseno.addLayout(_botonera(agregar, quitar, guardar))
        return pagina

    def _fila_turno(self, turno: str, franja: str) -> None:
        fila = self.turnos.rowCount()
        self.turnos.insertRow(fila)
        self.turnos.setItem(fila, 0, _celda(turno, editable=True))
        self.turnos.setItem(fila, 1, _celda(franja, editable=True))

    def _cargar_turnos(self) -> None:
        self.turnos.setRowCount(0)
        for franja in self.estado.config.turnos:
            self._fila_turno(franja.turno, franja.texto)

    def _guardar_turnos(self) -> None:
        franjas = {}
        for i in range(self.turnos.rowCount()):
            turno = (self.turnos.item(i, 0) or _celda("")).text().strip()
            texto = (self.turnos.item(i, 1) or _celda("")).text().strip()
            if turno or texto:
                franjas[turno] = texto
        try:
            if "" in franjas:
                raise ErrorAplicacion("Escriba el nombre de cada turno.")
            cfg.guardar_franjas(self.conexion, self.sesion, self.estado.config.archivo, franjas)
            self.estado.recargar_config()
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self._guardado([])

    # --- Técnicos ---

    def _crear_tecnicos(self) -> QWidget:
        self.tecnicos = _tabla(["Nombre en GLPI", "Nombre a mostrar", "Turno", "Activo", "Incluir en ranking"])
        guardar = QPushButton("Guardar cambios")
        guardar.clicked.connect(self._guardar_tecnicos)
        pagina = QWidget()
        diseno = QVBoxLayout(pagina)
        nota = QLabel("Los técnicos se crean solos al importar. Complete su turno; desmarque «Activo» si ya no "
                      "pertenece al equipo e «Incluir en ranking» durante vacaciones o ausencias.")
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        diseno.addWidget(nota)
        diseno.addWidget(self.tecnicos)
        diseno.addLayout(_botonera(guardar))
        return pagina

    def _cargar_tecnicos(self) -> None:
        filas = cfg.listar_tecnicos(self.conexion)
        self.tecnicos.setRowCount(len(filas))
        for i, f in enumerate(filas):
            nombre = _celda(f["nombre_glpi"])
            nombre.setData(Qt.ItemDataRole.UserRole, f["id"])
            self.tecnicos.setItem(i, 0, nombre)
            self.tecnicos.setItem(i, 1, _celda(f["nombre_mostrar"], editable=True))
            turno = QComboBox()
            turno.addItem("(sin turno)", None)
            for t in TURNOS_TECNICO:
                turno.addItem(t, t)
            turno.setCurrentIndex(max(0, turno.findData(f["turno"])))
            self.tecnicos.setCellWidget(i, 2, turno)
            self.tecnicos.setItem(i, 3, _casilla(bool(f["activo"])))
            self.tecnicos.setItem(i, 4, _casilla(bool(f["incluir_en_ranking"])))

    def _guardar_tecnicos(self) -> None:
        errores = []
        for i in range(self.tecnicos.rowCount()):
            try:
                cfg.actualizar_tecnico(
                    self.conexion, self.sesion, self.tecnicos.item(i, 0).data(Qt.ItemDataRole.UserRole),
                    nombre_mostrar=self.tecnicos.item(i, 1).text(),
                    turno=self.tecnicos.cellWidget(i, 2).currentData(),
                    activo=_marcada(self.tecnicos, i, 3),
                    incluir_en_ranking=_marcada(self.tecnicos, i, 4),
                )
            except ErrorAplicacion as error:
                errores.append(f"{self.tecnicos.item(i, 0).text()}: {error.mensaje}")
        self._guardado(errores)

    # --- Estaciones (IMP-07) ---

    def _crear_estaciones(self) -> QWidget:
        self.estaciones = _tabla(["Nombre", "Cliente", "Incluir en SEGMOV", "Activa", "Tickets asignados"])
        nueva = QPushButton("Nueva estación…")
        guardar = QPushButton("Guardar cambios")
        nueva.clicked.connect(self._nueva_estacion)
        guardar.clicked.connect(self._guardar_estaciones)
        pagina = QWidget()
        diseno = QVBoxLayout(pagina)
        nota = QLabel("Catálogo de estaciones para la clasificación manual. «Incluir en SEGMOV» indica si la "
                      "estación entra en la distribución mensual de horas (REP-08).")
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        diseno.addWidget(nota)
        diseno.addWidget(self.estaciones)
        diseno.addLayout(_botonera(nueva, guardar))
        return pagina

    def _cargar_estaciones(self) -> None:
        filas = clasificacion.listar_estaciones(self.conexion)
        self.estaciones.setRowCount(len(filas))
        for i, f in enumerate(filas):
            nombre = _celda(f["nombre"], editable=True)
            nombre.setData(Qt.ItemDataRole.UserRole, f["id"])
            self.estaciones.setItem(i, 0, nombre)
            self.estaciones.setItem(i, 1, _celda(f["cliente"], editable=True))
            self.estaciones.setItem(i, 2, _casilla(bool(f["incluir_segmov"])))
            self.estaciones.setItem(i, 3, _casilla(bool(f["activo"])))
            self.estaciones.setItem(i, 4, _celda(f["tickets"]))

    def _nueva_estacion(self) -> None:
        nombre, aceptado = QInputDialog.getText(self, "Nueva estación", "Nombre de la estación:")
        if not aceptado:
            return
        cliente, _ = QInputDialog.getText(self, "Nueva estación", "Cliente (opcional):")
        try:
            clasificacion.guardar_estacion(self.conexion, self.sesion, nombre=nombre, cliente=cliente)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self._guardado([])

    def _guardar_estaciones(self) -> None:
        errores = []
        for i in range(self.estaciones.rowCount()):
            try:
                clasificacion.guardar_estacion(
                    self.conexion, self.sesion,
                    estacion_id=self.estaciones.item(i, 0).data(Qt.ItemDataRole.UserRole),
                    nombre=self.estaciones.item(i, 0).text(),
                    cliente=self.estaciones.item(i, 1).text(),
                    incluir_segmov=_marcada(self.estaciones, i, 2),
                    activo=_marcada(self.estaciones, i, 3),
                )
            except ErrorAplicacion as error:
                errores.append(error.mensaje)
        self._guardado(errores)

    # --- Festivos ---

    def _crear_festivos(self) -> QWidget:
        self.festivos = _tabla(["Fecha", "Descripción"])
        self.festivos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.fecha_festivo = QDateEdit(QDate.currentDate(), calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.descripcion_festivo = QLineEdit(placeholderText="Descripción")
        agregar = QPushButton("Agregar")
        eliminar = QPushButton("Eliminar seleccionado")
        eliminar.setObjectName("secundario")
        self.anio_festivos = QSpinBox(minimum=2000, maximum=2100, value=reloj.ahora().year)
        proponer = QPushButton("Proponer festivos de Colombia…")
        agregar.clicked.connect(self._agregar_festivo)
        eliminar.clicked.connect(self._eliminar_festivo)
        proponer.clicked.connect(self._proponer_festivos)
        fila = QHBoxLayout()
        for widget in (self.fecha_festivo, self.descripcion_festivo, agregar, eliminar):
            fila.addWidget(widget)
        fila.addStretch()
        fila.addWidget(QLabel("Año:"))
        fila.addWidget(self.anio_festivos)
        fila.addWidget(proponer)
        pagina = QWidget()
        diseno = QVBoxLayout(pagina)
        diseno.addLayout(fila)
        diseno.addWidget(self.festivos)
        return pagina

    def _cargar_festivos(self) -> None:
        filas = cfg.listar_festivos(self.conexion)
        self.festivos.setRowCount(len(filas))
        for i, f in enumerate(filas):
            self.festivos.setItem(i, 0, _celda(f["fecha"]))
            self.festivos.setItem(i, 1, _celda(f["descripcion"]))

    def _agregar_festivo(self) -> None:
        dia = self.fecha_festivo.date()
        try:
            cfg.agregar_festivos(self.conexion, self.sesion,
                                 [(date(dia.year(), dia.month(), dia.day()), self.descripcion_festivo.text())])
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.descripcion_festivo.clear()
        self._guardado([], cambios=False)

    def _eliminar_festivo(self) -> None:
        fila = self.festivos.currentRow()
        if fila < 0:
            return
        cfg.eliminar_festivo(self.conexion, self.sesion, date.fromisoformat(self.festivos.item(fila, 0).text()))
        self._guardado([], cambios=False)

    def _proponer_festivos(self) -> None:
        propuesta = cfg.proponer_festivos(self.anio_festivos.value())
        lista = "\n".join(f"{d:%d/%m/%Y} – {n}" for d, n in propuesta)
        if confirmar(f"Festivos de ley de Colombia en {self.anio_festivos.value()}:\n\n{lista}\n\n"
                     "Revíselos. ¿Agregarlos a la tabla de festivos?", self):
            agregados = cfg.agregar_festivos(self.conexion, self.sesion, propuesta)
            mostrar_info(f"Se agregaron {agregados} festivos (los que ya existían no se duplicaron).", self)
            self._guardado([], cambios=False)

    # --- Usuarios ---

    def _crear_usuarios(self) -> QWidget:
        self.usuarios = _tabla(["Nombre", "Perfil", "Técnico asociado", "Activo", "Creado"])
        self.usuarios.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        nuevo = QPushButton("Nuevo usuario…")
        activar = QPushButton("Activar / desactivar")
        activar.setObjectName("secundario")
        pin = QPushButton("Restablecer PIN…")
        pin.setObjectName("secundario")
        nuevo.clicked.connect(self._nuevo_usuario)
        activar.clicked.connect(self._alternar_usuario)
        pin.clicked.connect(self._restablecer_pin)
        pagina = QWidget()
        diseno = QVBoxLayout(pagina)
        nota = QLabel("Consulta con técnico asociado: ve el equipo y sus propias métricas. Consulta sin técnico "
                      "(jefatura): ve solo los indicadores del equipo.")
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        diseno.addWidget(nota)
        diseno.addWidget(self.usuarios)
        diseno.addLayout(_botonera(nuevo, activar, pin))
        return pagina

    def _cargar_usuarios(self) -> None:
        filas = seguridad.listar_usuarios(self.conexion, self.sesion)
        self.usuarios.setRowCount(len(filas))
        for i, f in enumerate(filas):
            nombre = _celda(f["nombre"])
            nombre.setData(Qt.ItemDataRole.UserRole, (f["id"], bool(f["activo"])))
            self.usuarios.setItem(i, 0, nombre)
            self.usuarios.setItem(i, 1, _celda(NOMBRE_PERFIL[f["perfil"]]))
            self.usuarios.setItem(i, 2, _celda(f["tecnico"] or "—"))
            self.usuarios.setItem(i, 3, _celda("Sí" if f["activo"] else "No"))
            self.usuarios.setItem(i, 4, _celda(f["creado_en"][:16]))

    def _usuario_elegido(self) -> tuple[int, bool] | None:
        fila = self.usuarios.currentRow()
        return None if fila < 0 else self.usuarios.item(fila, 0).data(Qt.ItemDataRole.UserRole)

    def _nuevo_usuario(self) -> None:
        dialogo = DialogoUsuario(self.conexion, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            seguridad.crear_usuario(self.conexion, self.sesion, **dialogo.datos())
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self._guardado([])

    def _alternar_usuario(self) -> None:
        elegido = self._usuario_elegido()
        if elegido is None:
            return
        try:
            seguridad.cambiar_estado_usuario(self.conexion, self.sesion, elegido[0], not elegido[1])
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self._guardado([])

    def _restablecer_pin(self) -> None:
        elegido = self._usuario_elegido()
        if elegido is None:
            return
        pin, aceptado = QInputDialog.getText(self, "Restablecer PIN", "PIN nuevo (4 a 12 dígitos):",
                                             QLineEdit.EchoMode.Password)
        if not aceptado:
            return
        try:
            seguridad.restablecer_pin(self.conexion, self.sesion, elegido[0], pin)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self._guardado([])

    # --- Respaldos ---

    def _crear_respaldos(self) -> QWidget:
        self.respaldos = _tabla(["Fecha", "Motivo", "Tamaño", "Archivo"])
        self.respaldos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        crear = QPushButton("Crear respaldo ahora")
        restaurar = QPushButton("Restaurar seleccionado…")
        restaurar.setObjectName("secundario")
        crear.clicked.connect(self._crear_respaldo)
        restaurar.clicked.connect(self._restaurar)
        pagina = QWidget()
        diseno = QVBoxLayout(pagina)
        nota = QLabel(f"Respaldos automáticos: antes de cada importación y uno diario. Se conservan "
                      f"{self.estado.config.general.retencion_respaldos} días (config.ini). Antes de restaurar se "
                      "respalda la base actual.")
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        diseno.addWidget(nota)
        diseno.addWidget(self.respaldos)
        diseno.addLayout(_botonera(crear, restaurar))
        return pagina

    def _cargar_respaldos(self) -> None:
        lista = respaldo.listar(self.estado.config.rutas.respaldos)
        self.respaldos.setRowCount(len(lista))
        for i, r in enumerate(lista):
            fecha = _celda(f"{r.fecha:%d/%m/%Y %H:%M:%S}")
            fecha.setData(Qt.ItemDataRole.UserRole, str(r.ruta))
            self.respaldos.setItem(i, 0, fecha)
            self.respaldos.setItem(i, 1, _celda(r.motivo.replace("_", " ")))
            self.respaldos.setItem(i, 2, _celda(f"{r.tamano_bytes / 1024:,.0f} KB".replace(",", ".")))
            self.respaldos.setItem(i, 3, _celda(r.ruta.name))

    def _crear_respaldo(self) -> None:
        ruta = respaldo.respaldar(self.conexion, self.estado.config.rutas.respaldos, "manual")
        mostrar_info(f"Respaldo creado:\n{ruta.name}", self)
        self._cargar_respaldos()

    def _restaurar(self) -> None:
        fila = self.respaldos.currentRow()
        if fila < 0:
            return
        ruta = Path(self.respaldos.item(fila, 0).data(Qt.ItemDataRole.UserRole))
        if not confirmar(f"¿Restaurar la base de datos desde «{ruta.name}»?\n\nSe perderán los cambios posteriores "
                         "a ese respaldo, pero antes se guardará un respaldo de la base actual.", self):
            return
        try:
            previo = respaldo.restaurar(self.conexion, self.sesion, ruta, self.estado.config.rutas.respaldos)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        mostrar_info(f"Base de datos restaurada.\nRespaldo de la base anterior: {previo.name}", self)
        self._guardado([], cambios=False)

    # --- Perfiles de importación ---

    def _crear_perfiles(self) -> QWidget:
        self.perfiles = _tabla(["Nombre", "Separador", "Codificación", "Formato de fecha", "Columnas asociadas"])
        self.perfiles.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        eliminar = QPushButton("Eliminar seleccionado")
        eliminar.setObjectName("secundario")
        eliminar.clicked.connect(self._eliminar_perfil)
        pagina = QWidget()
        diseno = QVBoxLayout(pagina)
        diseno.addWidget(self.perfiles)
        diseno.addLayout(_botonera(eliminar))
        return pagina

    def _cargar_perfiles(self) -> None:
        lista = mapeo.listar_perfiles(self.conexion)
        self.perfiles.setRowCount(len(lista))
        for i, p in enumerate(lista):
            nombre = _celda(p.nombre)
            nombre.setData(Qt.ItemDataRole.UserRole, p.id)
            self.perfiles.setItem(i, 0, nombre)
            self.perfiles.setItem(i, 1, _celda({";": ";", ",": ",", "\t": "Tabulador", "|": "|"}.get(p.separador, p.separador)))
            self.perfiles.setItem(i, 2, _celda(p.codificacion))
            self.perfiles.setItem(i, 3, _celda(formato_legible(p.formato_fecha)))
            self.perfiles.setItem(i, 4, _celda(len(p.mapeo.columnas)))

    def _eliminar_perfil(self) -> None:
        fila = self.perfiles.currentRow()
        if fila < 0 or not confirmar("¿Eliminar el perfil seleccionado?", self):
            return
        try:
            mapeo.eliminar_perfil(self.conexion, self.sesion, self.perfiles.item(fila, 0).data(Qt.ItemDataRole.UserRole))
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self._guardado([])


class DialogoUsuario(QDialog):
    def __init__(self, conexion, padre=None):
        super().__init__(padre)
        self.setWindowTitle("Nuevo usuario")
        self.nombre = QLineEdit()
        self.perfil = QComboBox()
        self.perfil.addItem("Consulta", seguridad.CONSULTA)
        self.perfil.addItem("Coordinador", seguridad.COORDINADOR)
        self.tecnico = QComboBox()
        self.tecnico.addItem("(ninguno: jefatura)", None)
        for fila in conexion.execute("SELECT id, nombre_mostrar FROM tecnico WHERE activo = 1 ORDER BY nombre_mostrar"):
            self.tecnico.addItem(fila["nombre_mostrar"], fila["id"])
        self.pin = QLineEdit(echoMode=QLineEdit.EchoMode.Password)
        formulario = QFormLayout(self)
        formulario.addRow("Nombre:", self.nombre)
        formulario.addRow("Perfil:", self.perfil)
        formulario.addRow("Técnico asociado:", self.tecnico)
        formulario.addRow("PIN (4 a 12 dígitos):", self.pin)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        formulario.addRow(botones)

    def datos(self) -> dict:
        return {"nombre": self.nombre.text(), "perfil": self.perfil.currentData(),
                "pin": self.pin.text(), "tecnico_id": self.tecnico.currentData()}
