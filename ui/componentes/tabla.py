"""Tabla con orden, filtro por columna, búsqueda y botón Exportar (spec 06)."""

from collections.abc import Callable
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRegularExpression, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from core import reloj
from core.errores import ErrorAplicacion
from core.reportes.formatos import Hoja, Reporte, Tabla, anonimizar, escribir_csv, escribir_excel
from ui.dialogos import mostrar_error, mostrar_info

ROL_ORDEN = Qt.ItemDataRole.UserRole + 1
TODAS = "Todas las columnas"


def es_vacio(valor) -> bool:
    """None, NaN o pd.NA (las tuplas y listas nunca son vacías aquí)."""
    if isinstance(valor, (list, tuple, dict)):
        return False
    try:
        return bool(pd.isna(valor))
    except (TypeError, ValueError):
        return False


def texto_celda(valor) -> str:
    if es_vacio(valor):
        return ""
    if isinstance(valor, float):
        return f"{round(valor, 2):g}"
    return str(valor)


class ModeloDataFrame(QAbstractTableModel):
    def __init__(self, color_fila: Callable[[dict], str | None] | None = None):
        super().__init__()
        self.datos = pd.DataFrame()
        self.color_fila = color_fila
        self._numericas: set[int] = set()

    def fijar(self, datos: pd.DataFrame) -> None:
        self.beginResetModel()
        self.datos = datos.reset_index(drop=True)
        self._numericas = {
            i for i, c in enumerate(self.datos.columns) if pd.api.types.is_numeric_dtype(self.datos[c])
        }
        self.endResetModel()

    def rowCount(self, padre=QModelIndex()) -> int:
        return 0 if padre.isValid() else len(self.datos)

    def columnCount(self, padre=QModelIndex()) -> int:
        return 0 if padre.isValid() else len(self.datos.columns)

    def data(self, indice: QModelIndex, rol=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        valor = self.datos.iat[indice.row(), indice.column()]
        if rol == Qt.ItemDataRole.DisplayRole:
            return texto_celda(valor)
        if rol == ROL_ORDEN:
            vacio = es_vacio(valor)
            if indice.column() in self._numericas:
                return float("-inf") if vacio else float(valor)
            return "" if vacio else str(valor)
        if rol == Qt.ItemDataRole.BackgroundRole and self.color_fila:
            color = self.color_fila(self.fila(indice.row()))
            return QColor(color) if color else None
        if rol == Qt.ItemDataRole.TextAlignmentRole and indice.column() in self._numericas:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, seccion, orientacion, rol=Qt.ItemDataRole.DisplayRole):
        if rol == Qt.ItemDataRole.DisplayRole and orientacion == Qt.Orientation.Horizontal:
            return str(self.datos.columns[seccion])
        return None

    def fila(self, numero: int) -> dict:
        return self.datos.iloc[numero].to_dict()


class TablaDatos(QWidget):
    """Tabla filtrable y exportable. `columnas_personales` habilita «Anonimizar» (RNF-08)."""

    fila_activada = Signal(dict)

    def __init__(self, estado, titulo: str, columnas_personales: tuple[str, ...] = (),
                 color_fila: Callable[[dict], str | None] | None = None, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.titulo = titulo
        self.columnas_personales = columnas_personales
        self.modelo = ModeloDataFrame(color_fila)
        self.filtro = QSortFilterProxyModel(self)
        self.filtro.setSourceModel(self.modelo)
        self.filtro.setSortRole(ROL_ORDEN)
        self.filtro.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.filtro.setFilterKeyColumn(-1)

        self.busqueda = QLineEdit(placeholderText="Buscar…")
        self.busqueda.setClearButtonEnabled(True)
        self.busqueda.textChanged.connect(self._filtrar)
        self.columna = QComboBox()
        self.columna.currentIndexChanged.connect(self._filtrar)
        self.conteo = QLabel()
        self.anonimizar = QCheckBox("Anonimizar personas al exportar")
        self.anonimizar.setVisible(bool(columnas_personales))
        boton_excel = QPushButton("Exportar Excel")
        boton_csv = QPushButton("Exportar CSV")
        boton_csv.setObjectName("secundario")
        boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        boton_csv.clicked.connect(lambda: self.exportar("csv"))

        barra = QHBoxLayout()
        barra.addWidget(self.busqueda, 2)
        barra.addWidget(QLabel("en"))
        barra.addWidget(self.columna, 1)
        barra.addWidget(self.conteo)
        barra.addStretch()
        barra.addWidget(self.anonimizar)
        barra.addWidget(boton_excel)
        barra.addWidget(boton_csv)

        self.vista = QTableView()
        self.vista.setModel(self.filtro)
        # Sin columna de orden inicial: se conserva el orden en que vienen los datos
        self.vista.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.vista.setSortingEnabled(True)
        self.vista.setAlternatingRowColors(True)
        self.vista.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vista.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vista.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.vista.horizontalHeader().setStretchLastSection(True)
        self.vista.verticalHeader().setVisible(False)
        self.vista.doubleClicked.connect(self._activar)

        diseno = QVBoxLayout(self)
        diseno.setContentsMargins(0, 0, 0, 0)
        diseno.addLayout(barra)
        diseno.addWidget(self.vista)

    def fijar_datos(self, datos: pd.DataFrame) -> None:
        columna_actual = self.columna.currentText()
        self.modelo.fijar(datos)
        self.columna.blockSignals(True)
        self.columna.clear()
        self.columna.addItems([TODAS, *map(str, datos.columns)])
        if columna_actual in datos.columns:
            self.columna.setCurrentText(columna_actual)
        self.columna.blockSignals(False)
        self.vista.resizeColumnsToContents()
        for columna in range(self.modelo.columnCount()):
            if self.vista.columnWidth(columna) > 320:
                self.vista.setColumnWidth(columna, 320)
        self._filtrar()

    def datos_visibles(self) -> pd.DataFrame:
        """Filas que pasan el filtro, en el orden mostrado y sin las columnas ocultas."""
        filas = [self.filtro.mapToSource(self.filtro.index(i, 0)).row() for i in range(self.filtro.rowCount())]
        columnas = [c for i, c in enumerate(self.modelo.datos.columns) if not self.vista.isColumnHidden(i)]
        return self.modelo.datos.iloc[filas][columnas]

    def _filtrar(self) -> None:
        indice = self.columna.currentIndex()
        self.filtro.setFilterKeyColumn(indice - 1 if indice > 0 else -1)
        patron = QRegularExpression.escape(self.busqueda.text())
        self.filtro.setFilterRegularExpression(
            QRegularExpression(patron, QRegularExpression.PatternOption.CaseInsensitiveOption)
        )
        self.conteo.setText(f"{self.filtro.rowCount()} de {self.modelo.rowCount()} filas")

    def _activar(self, indice) -> None:
        self.fila_activada.emit(self.modelo.fila(self.filtro.mapToSource(indice).row()))

    def exportar(self, extension: str) -> None:
        datos = self.datos_visibles()
        if self.anonimizar.isChecked():
            datos = anonimizar(datos, self.columnas_personales)
        ahora = reloj.ahora()
        carpeta = self.estado.config.rutas.exportaciones / f"{ahora:%Y-%m}"
        carpeta.mkdir(parents=True, exist_ok=True)
        sugerido = carpeta / f"{self.titulo.replace(' ', '_')}_{ahora:%Y%m%d_%H%M%S}.{extension}"
        filtro = "Excel (*.xlsx)" if extension == "xlsx" else "CSV (*.csv)"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar", str(sugerido), filtro)
        if not ruta:
            return
        tabla = Tabla(self.titulo, datos)
        try:
            if extension == "xlsx":
                encabezado = {
                    "Período": self.estado.periodo.etiqueta,
                    "Generado": f"{ahora:%d/%m/%Y %H:%M}",
                    "Usuario": self.estado.sesion.nombre,
                }
                escribir_excel(Reporte(self.titulo, encabezado, [Hoja(self.titulo[:31], [tabla])]), Path(ruta))
            else:
                escribir_csv(tabla, Path(ruta))
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        mostrar_info(f"Archivo guardado en:\n{ruta}", self)
