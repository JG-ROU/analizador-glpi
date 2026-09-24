"""PAN-09: Hallazgos. Lista con filtros, revisión con comentario y tickets relacionados."""

import pandas as pd
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core.analisis import hallazgos as hal
from core.analisis import novedades
from core.errores import ErrorAplicacion
from ui.componentes.tabla import TablaDatos
from ui.dialogos import mostrar_error, mostrar_info
from ui.hilos import con_conexion, ejecutar
from ui.pantallas.novedades import DialogoDetalleTicket

COLOR_SEVERIDAD = {hal.ALTA: "#FFEBEE", hal.MEDIA: "#FFF8E1", hal.BAJA: "#F1F8E9"}
VISTAS = {
    "Abiertos (nuevos y revisados)": (hal.NUEVO, hal.REVISADO),
    "Nuevos": (hal.NUEVO,),
    "Revisados": (hal.REVISADO,),
    "Descartados": (hal.DESCARTADO,),
    "Cerrados": (hal.CERRADO,),
    "Todos": (),
}


class PantallaHallazgos(QWidget):
    titulo = "Hallazgos"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.vista = QComboBox()
        self.vista.addItems(list(VISTAS))
        self.severidad = QComboBox()
        self.severidad.addItem("(todas)", ())
        for sev in (hal.ALTA, hal.MEDIA, hal.BAJA):
            self.severidad.addItem(sev.capitalize(), (sev,))
        self.regla = QComboBox()
        self.regla.addItem("(todas)", ())
        for codigo, nombre in hal.REGLAS.items():
            self.regla.addItem(f"{codigo} {nombre}", (codigo,))
        for combo in (self.vista, self.severidad, self.regla):
            combo.activated.connect(self.actualizar)
        detectar = QPushButton("Detectar ahora")
        detectar.clicked.connect(self.detectar)
        filtros = QHBoxLayout()
        for texto, combo in (("Ver:", self.vista), ("Severidad:", self.severidad), ("Regla:", self.regla)):
            filtros.addWidget(QLabel(texto))
            filtros.addWidget(combo)
        filtros.addStretch()
        filtros.addWidget(detectar)

        self.tabla = TablaDatos(estado, "Hallazgos",
                                color_fila=lambda fila: COLOR_SEVERIDAD.get(fila.get("Severidad")))
        self.tabla.fila_activada.connect(lambda fila: self.ver_tickets())
        revisado = QPushButton("Marcar revisado…")
        descartar = QPushButton("Descartar…")
        descartar.setObjectName("secundario")
        tickets = QPushButton("Ver tickets relacionados")
        tickets.setObjectName("secundario")
        revisado.clicked.connect(lambda: self.revisar(hal.REVISADO))
        descartar.clicked.connect(lambda: self.revisar(hal.DESCARTADO))
        tickets.clicked.connect(self.ver_tickets)
        self.estado_deteccion = QLabel()
        self.estado_deteccion.setObjectName("nota")
        acciones = QHBoxLayout()
        for boton in (revisado, descartar, tickets):
            acciones.addWidget(boton)
        acciones.addStretch()
        acciones.addWidget(self.estado_deteccion)

        diseno = QVBoxLayout(self)
        diseno.addLayout(filtros)
        diseno.addWidget(self.tabla)
        diseno.addLayout(acciones)

    def actualizar(self) -> None:
        datos = hal.listar(self.estado.conexion, self.estado.sesion, VISTAS[self.vista.currentText()],
                           self.severidad.currentData(), self.regla.currentData())
        self.tabla.fijar_datos(datos)

    def detectar(self) -> None:
        self.estado_deteccion.setText("Detectando…")
        ejecutar(self, con_conexion(self.estado, lambda conexion, avance: hal.detectar(conexion)),
                 self._detectado, self._fallo)

    def _detectado(self, resumen: hal.ResumenDeteccion) -> None:
        self.estado_deteccion.setText(
            f"{resumen.nuevos} nuevos, {resumen.actualizados} actualizados, {resumen.cerrados} cerrados")
        self.estado.datos_cambiados.emit()
        self.actualizar()

    def _fallo(self, mensaje: str) -> None:
        self.estado_deteccion.clear()
        mostrar_error(mensaje, self)

    def _elegido(self) -> dict | None:
        filas = self.tabla.filas_seleccionadas()
        if not filas:
            mostrar_error("Seleccione un hallazgo.", self)
            return None
        return filas[0]

    def revisar(self, nuevo_estado: str) -> None:
        fila = self._elegido()
        if fila is None:
            return
        titulo = "Descartar hallazgo" if nuevo_estado == hal.DESCARTADO else "Marcar como revisado"
        comentario, aceptado = QInputDialog.getText(self, titulo, "Comentario (obligatorio al descartar):",
                                                    QLineEdit.EchoMode.Normal, fila.get("Comentario") or "")
        if not aceptado:
            return
        try:
            hal.revisar(self.estado.conexion, self.estado.sesion, int(fila["ID"]), nuevo_estado, comentario)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.estado.datos_cambiados.emit()
        self.actualizar()

    def ver_tickets(self) -> None:
        fila = self._elegido()
        if fila is None:
            return
        ids = hal.tickets_de(self.estado.conexion, int(fila["ID"]))
        if not ids:
            mostrar_info("Este hallazgo no tiene tickets relacionados.", self)
            return
        DialogoTicketsHallazgo(self.estado, fila["Descripción"], ids, self).exec()


class DialogoTicketsHallazgo(QDialog):
    def __init__(self, estado, descripcion: str, ids: list[int], padre=None):
        super().__init__(padre)
        self.estado = estado
        self.setWindowTitle("Tickets relacionados")
        self.resize(900, 460)
        texto = QLabel(descripcion)
        texto.setWordWrap(True)
        tabla = TablaDatos(estado, "Tickets del hallazgo", columnas_personales=("Autor", "Técnico"))
        marcas = ", ".join("?" * len(ids))
        filas = estado.conexion.execute(
            f"SELECT t.id_glpi, t.titulo, t.estado, t.prioridad, t.fecha_apertura, k.nombre_mostrar AS tecnico "
            f"FROM ticket t LEFT JOIN tecnico k ON k.id = t.tecnico_principal_id WHERE t.id_glpi IN ({marcas}) "
            "ORDER BY t.fecha_apertura", ids,
        ).fetchall()
        tabla.fijar_datos(pd.DataFrame(
            [{"ID": f["id_glpi"], "Título": f["titulo"], "Estado": f["estado"], "Prioridad": f["prioridad"],
              "Apertura": f["fecha_apertura"][:16], "Técnico": f["tecnico"]} for f in filas]
        ))
        tabla.fila_activada.connect(self._abrir)
        diseno = QVBoxLayout(self)
        diseno.addWidget(texto)
        diseno.addWidget(tabla)

    def _abrir(self, fila: dict) -> None:
        try:
            detalle = novedades.detalle(self.estado.conexion, self.estado.sesion, int(fila["ID"]))
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        DialogoDetalleTicket(detalle, self, self.estado).exec()
