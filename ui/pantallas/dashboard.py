"""PAN-03: Dashboard. Tarjetas de KPIs visibles, criticidad global y gráficos.

Los cálculos y las figuras se preparan en un hilo de trabajo con su propia
conexión; la pantalla muestra cuánto tardó (CA-07: menos de 2 s).
"""

import logging
import time

from PySide6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.analisis import hallazgos, semaforo, series
from core.analisis.kpis import CalculadoraKPI, criticidad_global
from core.errores import ErrorAplicacion
from core.reportes import catalogo, graficos
from core.reportes.graficos import COLORES_SEMAFORO
from ui.componentes.graficos import Grafico
from ui.componentes.tarjeta_kpi import TarjetaKPI
from ui.dialogos import mostrar_error, mostrar_info
from ui.hilos import con_conexion, ejecutar

log = logging.getLogger(__name__)

TARJETAS_POR_FILA = 5
MAXIMO_HALLAZGOS = 6
GRAFICOS = ("recibidos", "backlog", "prioridad", "estado", "carga", "brecha")


def calcular_tablero(conexion, sesion, periodo, filtros) -> dict:
    """Todo lo que muestra el dashboard. Se ejecuta fuera del hilo de la interfaz."""
    inicio = time.perf_counter()
    calc = CalculadoraKPI(conexion, sesion)
    resultados = calc.calcular_visibles(periodo, filtros)
    figuras = {
        "recibidos": graficos.recibidos_resueltos(series.recibidos_resueltos(calc, periodo, filtros)),
        "backlog": graficos.backlog(series.backlog(calc, periodo, filtros)),
        "prioridad": graficos.barras(
            series.abiertos_por_prioridad(calc, periodo, filtros), "Abiertos al corte por prioridad",
            graficos.COLORES_PRIORIDAD,
        ),
        "estado": graficos.barras(
            series.recibidos_por_estado(conexion, calc, periodo, filtros), "Recibidos por estado actual"
        ),
        "carga": graficos.carga_por_tecnico(series.carga_por_tecnico(conexion, calc, periodo, filtros)),
        "brecha": graficos.brecha_vs_meta(series.brechas(resultados, calc.definiciones)),
    }
    descripciones = {codigo: fila["descripcion"] for codigo, fila in calc.definiciones.items()}
    nuevos = hallazgos.listar(conexion, sesion, estados=(hallazgos.NUEVO,))
    return {
        "hallazgos": nuevos.head(MAXIMO_HALLAZGOS),
        "hallazgos_conteo": {sev: int((nuevos["Severidad"] == sev).sum()) for sev in (hallazgos.ALTA, hallazgos.MEDIA,
                                                                                         hallazgos.BAJA)},
        "resultados": resultados,
        "criticidad": criticidad_global(resultados),
        "figuras": figuras,
        "descripciones": descripciones,
        "segundos": time.perf_counter() - inicio,
    }


class PantallaDashboard(QWidget):
    titulo = "Dashboard"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.criticidad = QLabel()
        self.criticidad.setStyleSheet("font-size: 13pt; font-weight: 600;")
        self.tiempo = QLabel()
        self.tiempo.setObjectName("nota")
        exportar_excel = QPushButton("REP-01 en Excel")
        exportar_csv = QPushButton("REP-01 en CSV")
        exportar_csv.setObjectName("secundario")
        exportar_excel.clicked.connect(lambda: self.exportar(catalogo.EXCEL))
        exportar_csv.clicked.connect(lambda: self.exportar(catalogo.CSV))
        cabecera = QHBoxLayout()
        cabecera.addWidget(self.criticidad)
        cabecera.addStretch()
        cabecera.addWidget(self.tiempo)
        cabecera.addWidget(exportar_excel)
        cabecera.addWidget(exportar_csv)

        self.tarjetas = QGridLayout()
        self.graficos = {nombre: Grafico() for nombre in GRAFICOS}
        cuadricula = QGridLayout()
        for posicion, nombre in enumerate(GRAFICOS):
            caja = QGroupBox()
            QVBoxLayout(caja).addWidget(self.graficos[nombre])
            cuadricula.addWidget(caja, posicion // 3, posicion % 3)
        caja_hallazgos = QGroupBox("Hallazgos nuevos")
        self.hallazgos_conteo = QLabel()
        self.hallazgos_conteo.setStyleSheet("font-weight: 600;")
        self.hallazgos_lista = QLabel()
        self.hallazgos_lista.setWordWrap(True)
        diseno_hallazgos = QVBoxLayout(caja_hallazgos)
        diseno_hallazgos.addWidget(self.hallazgos_conteo)
        diseno_hallazgos.addWidget(self.hallazgos_lista)

        contenido = QWidget()
        diseno = QVBoxLayout(contenido)
        diseno.addLayout(cabecera)
        diseno.addLayout(self.tarjetas)
        diseno.addWidget(caja_hallazgos)
        diseno.addLayout(cuadricula)
        diseno.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(contenido)
        QVBoxLayout(self).addWidget(desplazable)

    def actualizar(self) -> None:
        estado = self.estado
        sesion, periodo, filtros = estado.sesion, estado.periodo, estado.filtros
        self._solicitud = getattr(self, "_solicitud", 0) + 1
        numero = self._solicitud
        self.tiempo.setText("Calculando…")
        ejecutar(
            self,
            con_conexion(estado, lambda conexion, avance: calcular_tablero(conexion, sesion, periodo, filtros)),
            lambda datos: self._mostrar(datos) if numero == self._solicitud else None,
            self._fallo,
        )

    def _mostrar(self, datos: dict) -> None:
        inicio = time.perf_counter()
        while self.tarjetas.count():
            self.tarjetas.takeAt(0).widget().deleteLater()
        for posicion, resultado in enumerate(datos["resultados"]):
            tarjeta = TarjetaKPI(resultado, datos["descripciones"].get(resultado.codigo, ""))
            self.tarjetas.addWidget(tarjeta, posicion // TARJETAS_POR_FILA, posicion % TARJETAS_POR_FILA)
        color = datos["criticidad"]
        self.criticidad.setText(f"Criticidad global: {semaforo.etiqueta(color)}")
        self.criticidad.setStyleSheet(
            f"font-size: 13pt; font-weight: 600; color: {COLORES_SEMAFORO.get(color, '#5A6B7B')};"
        )
        for nombre, figura in datos["figuras"].items():
            self.graficos[nombre].mostrar(figura)
        conteo = datos["hallazgos_conteo"]
        self.hallazgos_conteo.setText(
            f"✖ Alta: {conteo['ALTA']}    ▲ Media: {conteo['MEDIA']}    ● Baja: {conteo['BAJA']}"
        )
        lista = datos["hallazgos"]
        self.hallazgos_lista.setText(
            "\n".join(f"[{f['Severidad']}] {f['Regla']}: {f['Descripción']}" for _, f in lista.iterrows())
            or "Sin hallazgos nuevos."
        )
        total = datos["segundos"] + (time.perf_counter() - inicio)
        self.tiempo.setText(f"{self.estado.periodo.etiqueta} · calculado en {total:.2f} s")
        log.info("Dashboard de %s calculado en %.2f s", self.estado.periodo.codigo, total)

    def _fallo(self, mensaje: str) -> None:
        self.tiempo.setText("")
        mostrar_error(mensaje, self)

    def exportar(self, formato: str) -> None:
        solicitud = catalogo.SolicitudReporte(
            conexion=self.estado.conexion, sesion=self.estado.sesion, periodo=self.estado.periodo,
            carpeta_exportaciones=self.estado.config.rutas.exportaciones, filtros=self.estado.filtros,
        )
        try:
            ruta = catalogo.generar(solicitud, "REP-01", formato)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        mostrar_info(f"Reporte guardado en:\n{ruta}", self)
