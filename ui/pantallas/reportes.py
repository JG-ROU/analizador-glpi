"""PAN-12: Reportes. Catálogo según el perfil, formato, filtros de la barra superior y
generación en segundo plano (RNF-06). Paquete mensual y borradores de correo: F2-09."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from core import reloj
from core.analisis import periodos
from core.errores import ErrorAplicacion
from core.reportes import catalogo, paquete
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
        mensual = QGroupBox("Paquete mensual y correos (coordinador)")
        diseno_mensual = QHBoxLayout(mensual)
        paquete_boton = QPushButton("Generar paquete mensual…")
        paquete_boton.clicked.connect(self.generar_paquete)
        correo_boton = QPushButton("Borrador de correo: hallazgos ALTA")
        correo_boton.setObjectName("secundario")
        correo_boton.clicked.connect(self.borrador_hallazgos)
        resumenes_boton = QPushButton("Resúmenes semanales por técnico")
        resumenes_boton.setObjectName("secundario")
        resumenes_boton.setToolTip("Un borrador de correo por técnico con sus propias métricas y la "
                                   "retroalimentación de la última semana completa (nunca el ranking).")
        resumenes_boton.clicked.connect(self.resumenes_semanales)
        diseno_mensual.addWidget(paquete_boton)
        diseno_mensual.addWidget(correo_boton)
        diseno_mensual.addWidget(resumenes_boton)
        diseno_mensual.addStretch()
        mensual.setVisible(estado.sesion.es_coordinador)
        derecha = QVBoxLayout()
        derecha.addWidget(caja, 1)
        derecha.addWidget(mensual)
        diseno = QHBoxLayout(self)
        diseno.addWidget(self.lista, 1)
        diseno.addLayout(derecha, 2)
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

    # --- Paquete mensual (REP-10) y borradores .eml ---

    def generar_paquete(self) -> None:
        mes = self.estado.periodo if self.estado.periodo.granularidad == periodos.MES \
            else periodos.mes_de(reloj.ahora()).anterior()
        dialogo = DialogoPaquete(mes, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        estado, resumen, plan = self.estado, dialogo.resumen.toPlainText(), dialogo.plan.toPlainText()
        carpeta = estado.config.rutas.exportaciones
        self.resultado.setText(f"Generando el paquete de {mes.etiqueta}…")
        ejecutar(self, con_conexion(estado, lambda conexion, avance: paquete.generar(
            conexion, estado.sesion, mes, carpeta, resumen, plan)), self._paquete_generado, self._fallo)

    def _paquete_generado(self, resultado: paquete.Paquete) -> None:
        self.ultimo = resultado.pdf
        self.abrir.setEnabled(True)
        self.resultado.setText(f"Paquete generado:\n{resultado.pdf}\n{resultado.excel}\n"
                               f"Borrador de correo con el PDF adjunto: {resultado.correo.name}")
        self.estado.datos_cambiados.emit()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(resultado.correo)))

    def borrador_hallazgos(self) -> None:
        try:
            ruta = paquete.borrador_hallazgos_altos(self.estado.conexion, self.estado.sesion,
                                                    self.estado.config.rutas.exportaciones)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.resultado.setText(f"Borrador de correo guardado en:\n{ruta}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ruta)))

    def resumenes_semanales(self) -> None:
        estado = self.estado
        semana = paquete.semana_resumen(reloj.ahora())
        self.resultado.setText(f"Generando los resúmenes de la semana {semana.etiqueta}…")
        ejecutar(self, con_conexion(estado, lambda conexion, avance: paquete.resumenes_semanales(
            conexion, estado.sesion, estado.config.rutas.exportaciones, semana)), self._resumenes_generados, self._fallo)

    def _resumenes_generados(self, rutas: list[Path]) -> None:
        carpeta = rutas[0].parent
        self.resultado.setText(f"{len(rutas)} borradores de resumen semanal guardados en:\n{carpeta}\n"
                               "Complete el destinatario de cada uno en Outlook antes de enviar.")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(carpeta)))

    def _abrir_carpeta(self) -> None:
        carpeta = self.estado.config.rutas.exportaciones
        carpeta.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(carpeta)))


class DialogoPaquete(QDialog):
    """Textos editables del paquete mensual antes de generarlo."""

    def __init__(self, mes: periodos.Periodo, padre=None):
        super().__init__(padre)
        self.setWindowTitle(f"Paquete mensual – {mes.etiqueta}")
        self.resize(640, 480)
        self.resumen = QPlainTextEdit()
        self.resumen.setPlaceholderText("Resumen ejecutivo del mes: principales resultados, novedades y riesgos.")
        self.plan = QPlainTextEdit()
        self.plan.setPlaceholderText("Plan de mejora: acciones, responsables y fechas.")
        nota = QLabel("Incluye REP-01, REP-09, tendencias de 6 meses, los 5 casos más repetidos, hallazgos y "
                      "SEGMOV (si ya se generó REP-08 para el mes). Se crea además un borrador de correo con el "
                      "PDF adjunto, dirigido al parámetro «correo_jefatura».")
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Generar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        diseno = QFormLayout(self)
        diseno.addRow(nota)
        diseno.addRow("Resumen ejecutivo:", self.resumen)
        diseno.addRow("Plan de mejora:", self.plan)
        diseno.addRow(botones)
