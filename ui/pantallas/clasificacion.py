"""PAN-15: Clasificación manual de tickets (IMP-07).

El coordinador elige estación, categoría, causa y tipo de solución en listas
desplegables y los aplica a uno o varios tickets seleccionados a la vez.
"""

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core import clasificacion as cl
from core.errores import ErrorAplicacion
from ui.componentes.tabla import TablaDatos
from ui.dialogos import confirmar, mostrar_error, mostrar_info

NO_CAMBIAR = object()
QUITAR = object()
COLOR_PENDIENTE = "#FFF8E1"


class PantallaClasificacion(QWidget):
    titulo = "Clasificación"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.vista = QComboBox()
        self.vista.addItem("Pendientes de clasificar", cl.PENDIENTES)
        self.vista.addItem("Todos los recibidos en el período", cl.TODOS)
        self.vista.activated.connect(self.actualizar)
        ayuda = QLabel("Seleccione uno o varios tickets (Ctrl o Mayús + clic), elija los valores y pulse «Aplicar». "
                       "La clasificación no se pierde al volver a importar.")
        ayuda.setObjectName("nota")
        ayuda.setWordWrap(True)
        cabecera = QHBoxLayout()
        cabecera.addWidget(QLabel("Ver:"))
        cabecera.addWidget(self.vista)
        cabecera.addWidget(ayuda, 1)

        self.tabla = TablaDatos(estado, "Clasificación",
                                color_fila=lambda fila: COLOR_PENDIENTE if fila.get("Pendiente") == "Sí" else None)

        self.combos: dict[str, QComboBox] = {campo: QComboBox() for campo in cl.CAMPOS}
        formulario = QFormLayout()
        for campo, combo in self.combos.items():
            combo.setMinimumWidth(360)
            formulario.addRow(f"{cl.ETIQUETAS[campo]}:", combo)
        aplicar = QPushButton("Aplicar a los seleccionados")
        aplicar.clicked.connect(self.aplicar)
        sugerir = QPushButton("Sugerir estación desde Ubicación…")
        sugerir.setObjectName("secundario")
        sugerir.clicked.connect(self.sugerir)
        botones = QVBoxLayout()
        botones.addWidget(aplicar)
        botones.addWidget(sugerir)
        botones.addStretch()
        caja = QGroupBox("Asignar a los tickets seleccionados")
        diseno_caja = QHBoxLayout(caja)
        diseno_caja.addLayout(formulario)
        diseno_caja.addLayout(botones)
        diseno_caja.addStretch()

        diseno = QVBoxLayout(self)
        diseno.addLayout(cabecera)
        diseno.addWidget(self.tabla, 1)
        diseno.addWidget(caja)

    def _cargar_opciones(self) -> None:
        for campo, combo in self.combos.items():
            combo.clear()
            combo.addItem("(no cambiar)", NO_CAMBIAR)
            combo.addItem("(quitar el valor)", QUITAR)
            for opcion in cl.opciones(self.estado.conexion, campo):
                combo.addItem(opcion.texto, opcion.valor)

    def actualizar(self) -> None:
        self._cargar_opciones()
        try:
            datos = cl.listar(self.estado.conexion, self.estado.sesion, self.estado.periodo, self.vista.currentData())
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.tabla.fijar_datos(datos)

    def _seleccionados(self) -> list[int]:
        return [int(f["ID"]) for f in self.tabla.filas_seleccionadas()]

    def aplicar(self) -> None:
        ids = self._seleccionados()
        if not ids:
            mostrar_error("Seleccione al menos un ticket.", self)
            return
        cambios = {}
        for campo, combo in self.combos.items():
            dato = combo.currentData()
            if dato is NO_CAMBIAR:
                continue
            cambios[campo] = None if dato is QUITAR else dato
        if not cambios:
            mostrar_error("Elija al menos un valor para asignar.", self)
            return
        try:
            cambiados = cl.clasificar(self.estado.conexion, self.estado.sesion, ids, cambios)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        for combo in self.combos.values():
            combo.setCurrentIndex(0)
        self.estado.datos_cambiados.emit()
        self.actualizar()
        mostrar_info(f"Se clasificaron {cambiados} ticket(s). Los cambios quedaron en el historial.", self)

    def sugerir(self) -> None:
        ids = self._seleccionados() or [int(i) for i in self.tabla.datos_visibles()["ID"]]
        sugerencias = cl.sugerir_estaciones(self.estado.conexion, ids)
        if not sugerencias:
            mostrar_info("No hay sugerencias: ninguna Ubicación coincide con una estación del catálogo "
                         "(o los tickets ya tienen estación).", self)
            return
        nombres = {o.valor: o.texto for o in cl.opciones(self.estado.conexion, cl.ESTACION)}
        por_estacion: dict[int, list[int]] = {}
        for ticket_id, estacion_id in sugerencias.items():
            por_estacion.setdefault(estacion_id, []).append(ticket_id)
        resumen = "\n".join(f"{nombres[e]}: {len(t)} ticket(s)" for e, t in por_estacion.items())
        if not confirmar(f"Estaciones sugeridas según la Ubicación de GLPI:\n\n{resumen}\n\n¿Asignarlas?", self):
            return
        try:
            for estacion_id, tickets in por_estacion.items():
                cl.clasificar(self.estado.conexion, self.estado.sesion, tickets, {cl.ESTACION: estacion_id})
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.estado.datos_cambiados.emit()
        self.actualizar()
