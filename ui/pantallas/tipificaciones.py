"""PAN-08: Tipificaciones. Distribución por familia y categoría, tendencia mensual
por familia, categorías que crecen, uso de OTR-01 y tickets sin categoría.
Usa la categoría asignada en la clasificación manual (IMP-07)."""

from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from core.analisis import distribucion, semaforo
from core.analisis.kpis import CalculadoraKPI
from core.reportes import graficos
from core.reportes.catalogo import formatear_valor
from ui.componentes.graficos import Grafico
from ui.componentes.tabla import TablaDatos


class PantallaTipificaciones(QWidget):
    titulo = "Tipificaciones"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.resumen = QLabel()
        self.resumen.setStyleSheet("font-weight: 600;")
        self.familias, self.tendencia = Grafico(), Grafico()
        self.categorias = TablaDatos(estado, "Categorías")
        self.crecen = TablaDatos(estado, "Categorías que crecen")
        cuadricula = QGridLayout()
        cuadricula.addWidget(self._caja("Distribución por familia", self.familias), 0, 0)
        cuadricula.addWidget(self._caja("Tendencia mensual por familia (6 meses)", self.tendencia), 0, 1)
        cuadricula.addWidget(self._caja("Categorías del período", self.categorias), 1, 0)
        cuadricula.addWidget(self._caja("Variación frente al promedio de 3 meses", self.crecen), 1, 1)
        contenido = QWidget()
        diseno = QVBoxLayout(contenido)
        nota = QLabel("Según la categoría asignada en Clasificación.")
        nota.setObjectName("nota")
        cabecera = QHBoxLayout()
        cabecera.addWidget(self.resumen, 1)
        cabecera.addWidget(nota)
        diseno.addLayout(cabecera)
        diseno.addLayout(cuadricula)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(contenido)
        QVBoxLayout(self).addWidget(desplazable)

    @staticmethod
    def _caja(titulo: str, widget: QWidget) -> QGroupBox:
        caja = QGroupBox(titulo)
        QVBoxLayout(caja).addWidget(widget)
        widget.setMinimumHeight(260)
        return caja

    def actualizar(self) -> None:
        e = self.estado
        familias = distribucion.distribucion_familias(e.conexion, e.sesion, e.periodo, e.filtros)
        self.familias.mostrar(graficos.barras(familias, "Tickets por familia"))
        self.tendencia.mostrar(graficos.lineas(
            distribucion.tendencia_familias(e.conexion, e.sesion, e.periodo, filtros=e.filtros), "Tickets por familia"))
        self.categorias.fijar_datos(distribucion.distribucion_categorias(e.conexion, e.sesion, e.periodo, e.filtros))
        self.crecen.fijar_datos(distribucion.categorias_que_crecen(e.conexion, e.sesion, e.periodo, e.filtros))
        otros = CalculadoraKPI(e.conexion, e.sesion).calcular("KPI-10", e.periodo, e.filtros, comparar=False)
        sin_categoria = familias.get(distribucion.SIN_CATEGORIA, 0)
        self.resumen.setText(
            f"Uso de OTR-01: {formatear_valor(otros, otros.valor)} ({semaforo.etiqueta(otros.semaforo)})    ·    "
            f"Tickets sin categoría asignada: {sin_categoria}"
        )
