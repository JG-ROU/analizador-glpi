"""PAN-06: Estaciones. Ranking por volumen, reincidencia y tiempo; detalle con
tendencia semanal, familias y casos repetidos; mapa de calor estación × familia.
Usa la estación asignada en la clasificación manual (IMP-07)."""

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QSplitter, QTabWidget, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

from core.analisis import distribucion
from core.reportes import graficos
from ui.componentes.graficos import Grafico
from ui.componentes.tabla import TablaDatos


class PantallaEstaciones(QWidget):
    titulo = "Estaciones"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        nota = QLabel("Según la estación asignada en Clasificación. Haga clic en una estación para ver su detalle.")
        nota.setObjectName("nota")
        self.ranking = TablaDatos(estado, "Estaciones")
        self.ranking.vista.clicked.connect(self._elegida)
        self.nombre = QLabel()
        self.nombre.setObjectName("tituloPantalla")
        self.tendencia, self.familias = Grafico(), Grafico()
        self.repetidos = TablaDatos(estado, "Casos repetidos de la estación")
        detalle = QWidget()
        diseno_detalle = QVBoxLayout(detalle)
        diseno_detalle.addWidget(self.nombre)
        graficos_fila = QHBoxLayout()
        graficos_fila.addWidget(self.tendencia)
        graficos_fila.addWidget(self.familias)
        diseno_detalle.addLayout(graficos_fila)
        caja = QGroupBox("Casos repetidos (HAL-01)")
        QVBoxLayout(caja).addWidget(self.repetidos)
        diseno_detalle.addWidget(caja)
        self.mapa = Grafico()
        self.mapa.setMinimumHeight(420)
        pestanas = QTabWidget()
        pestanas.addTab(detalle, "Detalle de la estación")
        pestanas.addTab(self.mapa, "Mapa de calor estación × familia")
        divisor = QSplitter(Qt.Orientation.Vertical)
        divisor.addWidget(self.ranking)
        divisor.addWidget(pestanas)
        divisor.setSizes([300, 520])
        diseno = QVBoxLayout(self)
        diseno.addWidget(nota)
        diseno.addWidget(divisor)

    def actualizar(self) -> None:
        e = self.estado
        tabla = distribucion.ranking_estaciones(e.conexion, e.sesion, e.periodo, e.filtros)
        self.ranking.fijar_datos(tabla)
        self.ranking.vista.setColumnHidden(list(tabla.columns).index("_id"), True)
        self.mapa.mostrar(graficos.mapa_calor(distribucion.mapa_calor(e.conexion, e.sesion, e.periodo, e.filtros)))
        con_id = tabla.dropna(subset=["_id"])
        if not con_id.empty:
            self._mostrar(int(con_id.iloc[0]["_id"]), con_id.iloc[0]["Estación"])
        else:
            self.nombre.setText("Sin estaciones con tickets en el período")

    def _elegida(self, indice) -> None:
        fila = self.ranking.modelo.fila(self.ranking.filtro.mapToSource(indice).row())
        if fila.get("_id") is not None and fila["_id"] == fila["_id"]:  # descarta NaN
            self._mostrar(int(fila["_id"]), fila["Estación"])

    def _mostrar(self, estacion_id: int, nombre: str) -> None:
        e = self.estado
        self.nombre.setText(nombre)
        self.tendencia.mostrar(graficos.barras(
            distribucion.tendencia_semanal_estacion(e.conexion, e.sesion, estacion_id, e.periodo),
            "Tickets por semana (8 semanas)"))
        self.familias.mostrar(graficos.barras(
            distribucion.familias_de_estacion(e.conexion, e.sesion, estacion_id, e.periodo),
            "Familias más frecuentes"))
        self.repetidos.fijar_datos(distribucion.casos_repetidos_de_estacion(e.conexion, nombre))
