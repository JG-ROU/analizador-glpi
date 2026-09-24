"""Selector de período: semana ISO, mes o rango (RN-01)."""

from datetime import date

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import QComboBox, QDateEdit, QHBoxLayout, QLabel, QWidget

from core.analisis import periodos

SEMANA, MES, RANGO = "Semana", "Mes", "Rango"


def _qfecha(dia: date) -> QDate:
    return QDate(dia.year, dia.month, dia.day)


def _fecha(qfecha: QDate) -> date:
    return date(qfecha.year(), qfecha.month(), qfecha.day())


class SelectorPeriodo(QWidget):
    cambiado = Signal(object)  # periodos.Periodo

    def __init__(self, inicial: periodos.Periodo, padre=None):
        super().__init__(padre)
        self.tipo = QComboBox()
        self.tipo.addItems([SEMANA, MES, RANGO])
        self.desde = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.hasta = QDateEdit(calendarPopup=True, displayFormat="dd/MM/yyyy")
        self.etiqueta = QLabel()
        self.etiqueta.setObjectName("nota")
        self.separador = QLabel("a")
        diseno = QHBoxLayout(self)
        diseno.setContentsMargins(0, 0, 0, 0)
        diseno.addWidget(QLabel("Período:"))
        for widget in (self.tipo, self.desde, self.separador, self.hasta, self.etiqueta):
            diseno.addWidget(widget)
        self._cargar(inicial)
        self.tipo.currentTextChanged.connect(self._emitir)
        self.desde.dateChanged.connect(self._emitir)
        self.hasta.dateChanged.connect(self._emitir)

    def _cargar(self, periodo: periodos.Periodo) -> None:
        textos = {periodos.SEMANA: SEMANA, periodos.MES: MES, periodos.RANGO: RANGO}
        self.tipo.setCurrentText(textos[periodo.granularidad])
        self.desde.setDate(_qfecha(periodo.inicio.date()))
        # El fin del período es exclusivo: el último día incluido es el anterior
        self.hasta.setDate(_qfecha(date.fromordinal(periodo.fin.date().toordinal() - 1)))
        self._actualizar_vista(periodo)

    def periodo(self) -> periodos.Periodo:
        desde = _fecha(self.desde.date())
        if self.tipo.currentText() == SEMANA:
            return periodos.semana_de(desde)
        if self.tipo.currentText() == MES:
            return periodos.mes_de(desde)
        hasta = _fecha(self.hasta.date())
        return periodos.rango(min(desde, hasta), max(desde, hasta))

    def _actualizar_vista(self, periodo: periodos.Periodo) -> None:
        es_rango = self.tipo.currentText() == RANGO
        self.hasta.setVisible(es_rango)
        self.separador.setVisible(es_rango)
        self.etiqueta.setText(periodo.etiqueta)

    def _emitir(self) -> None:
        periodo = self.periodo()
        self._actualizar_vista(periodo)
        self.cambiado.emit(periodo)
