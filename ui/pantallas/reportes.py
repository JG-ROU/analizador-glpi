"""PAN-12: Reportes. Catálogo según el perfil, formato, filtros de la barra superior y
generación en segundo plano (RNF-06). Paquete mensual y borradores de correo: F2-09."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from core.reportes import catalogo
from ui.dialogos import mostrar_error
from ui.hilos import con_conexion, ejecutar

NOMBRES_FORMATO = {catalogo.PDF: "PDF", catalogo.EXCEL: "Excel", catalogo.CSV: "CSV (tabla principal)"}


class PantallaReportes(QWidget):
    titulo = "Reportes"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.ultimo: Path | None = None
        self.lista = QListWidget()
        for definicion in catalogo.disponibles(estado.sesion):
            item = QListWidgetItem(f"{definicion.codigo}  {definicion.nombre}")
            item.setData(Qt.ItemDataRole.UserRole, definicion)
            self.lista.addItem(item)
        self.lista.currentItemChanged.connect(self._elegido)
        self.descripcion = QLabel()
        self.descripcion.setWordWrap(True)
        self.filtros = QLabel()
        self.filtros.setObjectName("nota")
        self.filtros.setWordWrap(True)
        self.formatos = QButtonGroup(self)
        fila_formatos = QHBoxLayout()
        for posicion, (clave, nombre) in enumerate(NOMBRES_FORMATO.items()):
            boton = QRadioButton(nombre)
            boton.setProperty("formato", clave)
            boton.setChecked(posicion == 0)
            self.formatos.addButton(boton)
            fila_formatos.addWidget(boton)
        fila_formatos.addStretch()
        self.horas = QLineEdit(placeholderText="por ejemplo 720")
        self.anonimizar = QCheckBox("Anonimizar autores y técnicos (para compartir fuera del equipo)")
        self.generar_boton = QPushButton("Generar reporte")
        self.generar_boton.clicked.connect(self.generar)
        self.abrir = QPushButton("Abrir archivo")
        self.abrir.setObjectName("secundario")
        self.abrir.setEnabled(False)
        self.abrir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ultimo))))
        self.carpeta = QPushButton("Abrir carpeta de exportaciones")
        self.carpeta.setObjectName("secundario")
        self.carpeta.clicked.connect(self._abrir_carpeta)
        self.resultado = QLabel()
        self.resultado.setWordWrap(True)

        formulario = QFormLayout()
        formulario.addRow("Descripción:", self.descripcion)
        formulario.addRow("Período y filtros:", self.filtros)
        formulario.addRow("Formato:", fila_formatos)
        formulario.addRow("Horas del mes (SEGMOV):", self.horas)
        formulario.addRow("", self.anonimizar)
        self.formulario = formulario
        botones = QHBoxLayout()
        for boton in (self.generar_boton, self.abrir, self.carpeta):
            botones.addWidget(boton)
        botones.addStretch()
        caja = QGroupBox("Generar")
        diseno_caja = QVBoxLayout(caja)
        diseno_caja.addLayout(formulario)
        diseno_caja.addLayout(botones)
        diseno_caja.addWidget(self.resultado)
        diseno_caja.addStretch()
        diseno = QHBoxLayout(self)
        diseno.addWidget(self.lista, 1)
        diseno.addWidget(caja, 2)
        self.lista.setCurrentRow(0)

    def actualizar(self) -> None:
        self.filtros.setText(
            f"{self.estado.periodo.etiqueta} · "
            f"{catalogo.describir_filtros(self.estado.conexion, self.estado.filtros)} "
            "(se cambian en la barra superior)"
        )

    def _definicion(self) -> catalogo.DefinicionReporte | None:
        item = self.lista.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _elegido(self) -> None:
        definicion = self._definicion()
        if definicion is None:
            return
        self.descripcion.setText(definicion.descripcion)
        self.formulario.setRowVisible(self.horas, definicion.pide_horas)

    def generar(self) -> None:
        definicion = self._definicion()
        if definicion is None:
            return
        total_horas = None
        if definicion.pide_horas:
            try:
                total_horas = float(self.horas.text().strip().replace(",", "."))
            except ValueError:
                mostrar_error("Indique el total de horas del mes para SEGMOV.", self)
                return
        formato = self.formatos.checkedButton().property("formato")
        estado = self.estado
        sesion, periodo, filtros = estado.sesion, estado.periodo, estado.filtros
        carpeta, anonimizar = estado.config.rutas.exportaciones, self.anonimizar.isChecked()

        def trabajo(conexion, avance):
            solicitud = catalogo.SolicitudReporte(
                conexion=conexion, sesion=sesion, periodo=periodo, carpeta_exportaciones=carpeta,
                filtros=filtros, total_horas=total_horas, anonimizar=anonimizar,
            )
            return catalogo.generar(solicitud, definicion.codigo, formato)

        self.generar_boton.setEnabled(False)
        self.resultado.setText(f"Generando {definicion.codigo}…")
        ejecutar(self, con_conexion(estado, trabajo), self._generado, self._fallo)

    def _generado(self, ruta: Path) -> None:
        self.generar_boton.setEnabled(True)
        self.ultimo = ruta
        self.abrir.setEnabled(True)
        self.resultado.setText(f"Reporte guardado en:\n{ruta}")
        if self._definicion() and self._definicion().pide_horas:
            self.estado.datos_cambiados.emit()

    def _fallo(self, mensaje: str) -> None:
        self.generar_boton.setEnabled(True)
        self.resultado.clear()
        mostrar_error(mensaje, self)

    def _abrir_carpeta(self) -> None:
        carpeta = self.estado.config.rutas.exportaciones
        carpeta.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(carpeta)))

