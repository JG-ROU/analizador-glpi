"""Pestaña de Importar para el CSV de seguimientos y tareas (Fase 3).

Mismo flujo que los tickets: archivo → autodetección → asociación de columnas →
vista previa validada → importar. Las notas ya cargadas no se duplican.
"""

from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.errores import ErrorAplicacion
from core.fuentes.fuente_csv import FORMATOS_FECHA, FuenteCSV
from core.importacion import seguimientos as seg
from core.importacion.validacion import ADVERTENCIA, ERROR, VALIDA, formato_legible
from ui.componentes.tabla import TablaDatos
from ui.dialogos import mostrar_error, mostrar_info
from ui.hilos import con_conexion, ejecutar

SIN_ASIGNAR = "(sin asignar)"
TEXTO_RESULTADO = {VALIDA: "✔ Válida", ADVERTENCIA: "▲ Advertencia", ERROR: "✖ Error"}
COLOR = {"✔ Válida": "#E8F5E9", "▲ Advertencia": "#FFF8E1", "✖ Error": "#FFEBEE"}


class PanelSeguimientos(QWidget):
    def __init__(self, estado, al_importar=None, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.al_importar = al_importar
        self.fuente: FuenteCSV | None = None
        self.resultado: seg.ResultadoSeguimientos | None = None
        elegir = QPushButton("Elegir CSV de seguimientos…")
        elegir.clicked.connect(self.elegir)
        self.ruta = QLabel("Ningún archivo elegido. Importe antes el CSV de tickets: las notas de tickets que no "
                           "están cargados se informan y no se importan.")
        self.ruta.setWordWrap(True)
        self.formato_fecha = QComboBox()
        for formato in FORMATOS_FECHA:
            self.formato_fecha.addItem(formato_legible(formato), formato)
        self.mapeo = QTableWidget(len(seg.CAMPOS_SEGUIMIENTO), 2)
        self.mapeo.setHorizontalHeaderLabels(["Campo del analizador", "Columna del archivo"])
        self.mapeo.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mapeo.verticalHeader().setVisible(False)
        for numero, campo in enumerate(seg.CAMPOS_SEGUIMIENTO):
            celda = QTableWidgetItem(campo.etiqueta + (" *" if campo.obligatorio else ""))
            celda.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.mapeo.setItem(numero, 0, celda)
            self.mapeo.setCellWidget(numero, 1, QComboBox())
        self.validar_boton = QPushButton("Validar vista previa")
        self.validar_boton.clicked.connect(self.validar)
        self.importar_boton = QPushButton("Importar notas válidas")
        self.importar_boton.clicked.connect(self.importar)
        self.progreso = QProgressBar()
        self.progreso.hide()
        self.resumen = QLabel()
        self.vista = TablaDatos(estado, "Vista previa de seguimientos", columnas_personales=("Autor",),
                                color_fila=lambda f: COLOR.get(f.get("Resultado")))
        formulario = QFormLayout()
        formulario.addRow("Formato de fecha:", self.formato_fecha)
        arriba = QHBoxLayout()
        arriba.addWidget(elegir)
        arriba.addWidget(self.ruta, 1)
        caja = QGroupBox("Asociación de columnas (* obligatorio)")
        diseno_caja = QHBoxLayout(caja)
        diseno_caja.addLayout(formulario)
        diseno_caja.addWidget(self.mapeo, 1)
        acciones = QHBoxLayout()
        for widget in (self.validar_boton, self.importar_boton):
            acciones.addWidget(widget)
        acciones.addWidget(self.progreso, 1)
        acciones.addWidget(self.resumen)
        diseno = QVBoxLayout(self)
        diseno.addLayout(arriba)
        diseno.addWidget(caja)
        diseno.addLayout(acciones)
        diseno.addWidget(self.vista, 1)
        self._habilitar()

    def _habilitar(self) -> None:
        self.validar_boton.setEnabled(self.fuente is not None)
        cargables = 0 if self.resultado is None else len(self.resultado.cargables)
        self.importar_boton.setEnabled(cargables > 0)
        self.importar_boton.setText(f"Importar notas válidas ({cargables})" if cargables else "Importar notas válidas")

    def elegir(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir CSV de seguimientos", "", "CSV (*.csv);;Todos (*.*)")
        if ruta:
            self.cargar_archivo(Path(ruta))

    def cargar_archivo(self, ruta: Path) -> None:
        try:
            self.fuente = FuenteCSV(ruta, tamano_bloque=self.estado.config.importacion.tamano_bloque)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.resultado = None
        self.ruta.setText(str(ruta))
        perfil = seg.perfil_guardado(self.estado.conexion, self.fuente.formato) or seg.proponer_perfil(self.fuente.formato)
        if perfil.formato_fecha:
            self.formato_fecha.setCurrentIndex(self.formato_fecha.findData(perfil.formato_fecha))
        for numero, campo in enumerate(seg.CAMPOS_SEGUIMIENTO):
            combo: QComboBox = self.mapeo.cellWidget(numero, 1)
            combo.clear()
            combo.addItems([SIN_ASIGNAR, *self.fuente.formato.encabezados])
            combo.setCurrentText(perfil.columnas.get(campo.nombre, SIN_ASIGNAR))
        self.vista.fijar_datos(pd.DataFrame())
        self._habilitar()

    def perfil(self) -> seg.PerfilSeguimientos:
        columnas = {}
        for numero, campo in enumerate(seg.CAMPOS_SEGUIMIENTO):
            texto = self.mapeo.cellWidget(numero, 1).currentText()
            if texto and texto != SIN_ASIGNAR:
                columnas[campo.nombre] = texto
        return seg.PerfilSeguimientos(seg.PREFIJO_PERFIL + "Exportación GLPI", self.fuente.formato,
                                      self.formato_fecha.currentData(), columnas)

    def validar(self) -> None:
        if self.fuente is None:
            return
        perfil, fuente, estado = self.perfil(), self.fuente, self.estado
        self._ocupado(True)
        ejecutar(self, con_conexion(estado, lambda conexion, avance: seg.validar(conexion, fuente.obtener_tickets(), perfil)),
                 self._validado, self._fallo)

    def _validado(self, resultado: seg.ResultadoSeguimientos) -> None:
        self._ocupado(False)
        self.resultado = resultado
        f = resultado.filas
        self.vista.fijar_datos(pd.DataFrame({
            "Fila": f["_fila"], "Resultado": f["resultado"].map(TEXTO_RESULTADO), "Motivos": f["motivos"],
            "Ticket": f["ticket_id"].astype(object), "Fecha": f["fecha"].map(lambda x: "" if pd.isna(x) else f"{x:%d/%m/%Y %H:%M}"),
            "Autor": f["autor"], "Tipo": f["tipo"], "Etiqueta": f["etiqueta"], "Contenido": f["contenido"].str.slice(0, 120),
        }))
        self.resumen.setText(f"{len(f)} notas: {resultado.conteo(VALIDA)} válidas, {resultado.conteo(ADVERTENCIA)} con "
                             f"advertencia, {resultado.conteo(ERROR)} con error")
        self._habilitar()

    def importar(self) -> None:
        if self.resultado is None:
            return
        perfil, fuente, resultado, estado = self.perfil(), self.fuente, self.resultado, self.estado
        sesion, config = estado.sesion, estado.config

        def trabajo(conexion, avance):
            return seg.importar(conexion, sesion, archivo=fuente.ruta.name, hash_archivo=fuente.hash, perfil=perfil,
                                validacion=resultado, carpeta_respaldos=config.rutas.respaldos,
                                retencion_respaldos=config.general.retencion_respaldos)

        self._ocupado(True)
        ejecutar(self, con_conexion(estado, trabajo), self._importado, self._fallo)

    def _importado(self, resumen: seg.ResumenSeguimientos) -> None:
        self._ocupado(False)
        self.resultado = None
        self._habilitar()
        self.estado.datos_cambiados.emit()
        if self.al_importar:
            self.al_importar()
        mostrar_info(f"Seguimientos importados.\n\nNotas nuevas: {resumen.nuevos}\nYa existían: {resumen.repetidos}\n"
                     f"Filas con error (no cargadas): {resumen.filas_error}\nTickets con notas: {len(resumen.tickets)}", self)

    def _ocupado(self, ocupado: bool) -> None:
        self.validar_boton.setEnabled(not ocupado)
        self.importar_boton.setEnabled(not ocupado)
        self.progreso.setVisible(ocupado)
        self.progreso.setRange(0, 0)
        if not ocupado:
            self._habilitar()

    def _fallo(self, mensaje: str) -> None:
        self._ocupado(False)
        mostrar_error(mensaje, self)
