"""PAN-14: Historial de cambios manuales, solo lectura (RNF-09)."""

import pandas as pd
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core import historial
from ui.componentes.tabla import TablaDatos

ENTIDADES = {
    None: "(todas)",
    "parametro": "Parámetros",
    "kpi_definicion": "KPIs",
    "tecnico": "Técnicos",
    "ticket_clasificacion": "Clasificación de tickets",
    "estacion": "Estaciones",
    "hallazgo": "Hallazgos",
    "segmov": "SEGMOV",
    "evaluacion": "Evaluaciones de calidad",
    "muestra_auditoria": "Muestra de auditoría",
    "snapshot": "Snapshots",
    "ticket": "Tickets (tipo de caso)",
    "usuario": "Usuarios",
    "festivo": "Festivos",
    "config.ini": "Turnos (config.ini)",
    "perfil_importacion": "Perfiles de importación",
    "importacion": "Importaciones",
    "base_datos": "Base de datos",
}
LIMITE = 5000


class PantallaHistorial(QWidget):
    titulo = "Historial"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.entidad = QComboBox()
        for codigo, nombre in ENTIDADES.items():
            self.entidad.addItem(nombre, codigo)
        self.entidad.activated.connect(self.actualizar)
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Tipo de cambio:"))
        fila.addWidget(self.entidad)
        fila.addStretch()
        nota = QLabel("El historial es de solo lectura: la base de datos impide modificar o borrar sus registros.")
        nota.setObjectName("nota")
        self.tabla = TablaDatos(estado, "Historial", columnas_personales=("Usuario",))
        diseno = QVBoxLayout(self)
        diseno.addLayout(fila)
        diseno.addWidget(nota)
        diseno.addWidget(self.tabla)

    def actualizar(self) -> None:
        filas = historial.consultar(self.estado.conexion, entidad=self.entidad.currentData(), limite=LIMITE)
        self.tabla.fijar_datos(pd.DataFrame(
            [
                {
                    "Fecha y hora": f["fecha_hora"][:19], "Usuario": f["usuario"] or "—",
                    "Tipo": ENTIDADES.get(f["entidad"], f["entidad"]), "Elemento": f["entidad_id"],
                    "Acción": f["accion"], "Campo": f["campo"], "Antes": f["valor_anterior"],
                    "Después": f["valor_nuevo"], "Nota": f["nota"],
                }
                for f in filas
            ],
            columns=["Fecha y hora", "Usuario", "Tipo", "Elemento", "Acción", "Campo", "Antes", "Después", "Nota"],
        ))
