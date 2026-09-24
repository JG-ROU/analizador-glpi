"""PAN-07: Responsables (sin calidad). El coordinador ve a todos los técnicos;
un usuario de consulta, solo sus propias métricas (CA-08)."""

import pandas as pd
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.analisis import estadistica as est
from core.analisis import responsables
from core.errores import ErrorAplicacion
from core.reportes import catalogo, graficos
from ui.componentes.graficos import Grafico
from ui.componentes.tabla import TablaDatos
from ui.dialogos import mostrar_error, mostrar_info


def tabla_metricas(lista: list[responsables.MetricasTecnico]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Técnico": m.nombre, "Turno": m.turno or "—", "Abiertos": m.abiertos,
                "Abiertos por prioridad": ", ".join(f"{k}: {v}" for k, v in m.abiertos_por_prioridad.items()) or "—",
                "Atendidos": m.atendidos, "Soluciones": m.soluciones, "Escalamientos": m.escalamientos,
                "% escalamiento": m.tasa_escalamiento, "Mediana resolución (h) ≈": m.mediana_resolucion,
                "P90 (h) ≈": m.p90_resolucion, "% SLA ≈": m.sla,
                "Resueltos sin cerrar (informativo)": m.sin_cerrar_cantidad, "Reaperturas": m.reaperturas,
                "Sin actualizar": m.sin_actualizar,
                "Muestra": est.AVISO_MUESTRA_PEQUENA if m.muestra_pequena else "", "_id": m.tecnico_id,
            }
            for m in lista
        ]
    )


class PantallaResponsables(QWidget):
    titulo = "Responsables"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.lista: list[responsables.MetricasTecnico] = []
        nota = QLabel(
            "La cantidad de tickets es informativa (carga), no una calificación. Los resueltos sin "
            "cerrar dependen del visto bueno del autor. Tiempos aproximados (≈) y sin descontar espera."
        )
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        rep_excel = QPushButton("REP-03 en Excel")
        rep_csv = QPushButton("REP-03 en CSV")
        rep_csv.setObjectName("secundario")
        rep_excel.clicked.connect(lambda: self.exportar(catalogo.EXCEL))
        rep_csv.clicked.connect(lambda: self.exportar(catalogo.CSV))
        cabecera = QHBoxLayout()
        cabecera.addWidget(nota, 1)
        cabecera.addWidget(rep_excel)
        cabecera.addWidget(rep_csv)
        self.tabla = TablaDatos(estado, "Responsables")
        self.tabla.fila_activada.connect(lambda fila: self._mostrar_tecnico(int(fila["_id"])))
        self.tabla.vista.clicked.connect(
            lambda indice: self._mostrar_tecnico(int(self.tabla.modelo.fila(self.tabla.filtro.mapToSource(indice).row())["_id"]))
        )
        self.semanal = Grafico()
        self.carga = Grafico()
        caja_semanal = QGroupBox("Atendidos por semana (técnico seleccionado)")
        QVBoxLayout(caja_semanal).addWidget(self.semanal)
        caja_carga = QGroupBox("Carga actual por prioridad")
        QVBoxLayout(caja_carga).addWidget(self.carga)
        graficos_fila = QHBoxLayout()
        graficos_fila.addWidget(caja_semanal)
        graficos_fila.addWidget(caja_carga)
        diseno = QVBoxLayout(self)
        diseno.addLayout(cabecera)
        diseno.addWidget(self.tabla, 2)
        diseno.addLayout(graficos_fila, 1)

    def actualizar(self) -> None:
        try:
            self.lista = responsables.metricas(self.estado.conexion, self.estado.sesion, self.estado.periodo)
        except ErrorAplicacion as error:
            self.tabla.fijar_datos(pd.DataFrame())
            mostrar_error(error.mensaje, self)
            return
        datos = tabla_metricas(self.lista)
        self.tabla.fijar_datos(datos)
        if "_id" in datos:
            self.tabla.vista.setColumnHidden(list(datos.columns).index("_id"), True)
        self.carga.mostrar(graficos.carga_por_tecnico(
            {m.nombre: m.abiertos_por_prioridad for m in self.lista if m.abiertos_por_prioridad}
        ))
        if self.lista:
            self._mostrar_tecnico(self.lista[0].tecnico_id)

    def _mostrar_tecnico(self, tecnico_id: int) -> None:
        try:
            serie = responsables.atendidos_por_semana(
                self.estado.conexion, self.estado.sesion, tecnico_id, self.estado.periodo
            )
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        nombre = next((m.nombre for m in self.lista if m.tecnico_id == tecnico_id), "")
        conteos = {f"Semana {s.inicio.isocalendar()[1]:02d}": n for s, n in serie}
        self.semanal.mostrar(graficos.barras(conteos, f"Atendidos por semana · {nombre}"))

    def exportar(self, formato: str) -> None:
        solicitud = catalogo.SolicitudReporte(
            conexion=self.estado.conexion, sesion=self.estado.sesion, periodo=self.estado.periodo,
            carpeta_exportaciones=self.estado.config.rutas.exportaciones, filtros=self.estado.filtros,
        )
        try:
            ruta = catalogo.generar(solicitud, "REP-03", formato)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        mostrar_info(f"Reporte guardado en:\n{ruta}", self)
