"""PAN-04: Novedades (tickets recientes y abiertos, accesos rápidos) y PAN-05: Detalle."""

import html

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QHeaderView, QAbstractItemView,
)

from core.analisis import calidad, novedades
from core.analisis.filtros import Filtros
from core.analisis.kpis import NOMBRE_PRIORIDAD
from core.analisis.series import NOMBRE_ESTADO
from core.dominio import NOMBRE_TIPO_CASO
from core.errores import ErrorAplicacion
from core.importacion import eventos as ev
from ui.componentes.tabla import TablaDatos
from ui.dialogos import mostrar_error
from ui.pantallas.calidad import DialogoEvaluacion

TODOS = "(todos)"
NOMBRE_EVENTO = {
    ev.ESCALAMIENTO: "Escalamiento",
    ev.SALIDA_ESCALADO: "Salida de escalado",
    ev.SOLUCION: "Solución",
    ev.CIERRE: "Cierre",
    ev.REAPERTURA: "Reapertura",
}
NOMBRE_ORIGEN = {ev.TRANSICION: "Entre importaciones", ev.PRIMERA_VEZ: "Primera vez (histórico aproximado)"}


class PantallaNovedades(QWidget):
    titulo = "Novedades"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.acceso = QComboBox()
        for codigo, nombre in novedades.ACCESOS_RAPIDOS.items():
            self.acceso.addItem(nombre, codigo)
        self.estado_ticket = QComboBox()
        self.estado_ticket.addItem(TODOS, None)
        for codigo, nombre in NOMBRE_ESTADO.items():
            self.estado_ticket.addItem(nombre, codigo)
        self.prioridad = QComboBox()
        self.prioridad.addItem(TODOS, None)
        for nivel in sorted(NOMBRE_PRIORIDAD, reverse=True):
            self.prioridad.addItem(NOMBRE_PRIORIDAD[nivel], nivel)
        self.tecnico = QComboBox()
        for combo in (self.acceso, self.estado_ticket, self.prioridad, self.tecnico):
            combo.activated.connect(self.actualizar)
        filtros = QHBoxLayout()
        for texto, combo in (("Ver:", self.acceso), ("Estado:", self.estado_ticket),
                             ("Prioridad:", self.prioridad), ("Técnico:", self.tecnico)):
            filtros.addWidget(QLabel(texto))
            filtros.addWidget(combo)
        filtros.addStretch()
        self.tabla = TablaDatos(estado, "Novedades", columnas_personales=("Autor", "Técnico"))
        self.tabla.fila_activada.connect(lambda fila: self.abrir_detalle(int(fila["ID"])))
        ayuda = QLabel("Doble clic en un ticket para ver su detalle.")
        ayuda.setObjectName("nota")
        diseno = QVBoxLayout(self)
        diseno.addLayout(filtros)
        diseno.addWidget(ayuda)
        diseno.addWidget(self.tabla)
        self._cargar_tecnicos()

    def _cargar_tecnicos(self) -> None:
        self.tecnico.clear()
        self.tecnico.addItem(TODOS, None)
        if self.estado.sesion.es_coordinador:
            for fila in self.estado.conexion.execute("SELECT id, nombre_mostrar FROM tecnico ORDER BY nombre_mostrar"):
                self.tecnico.addItem(fila["nombre_mostrar"], fila["id"])
        self.tecnico.setEnabled(self.estado.sesion.es_coordinador)

    def actualizar(self) -> None:
        if self.tecnico.count() <= 1 and self.estado.sesion.es_coordinador:
            self._cargar_tecnicos()
        base = self.estado.filtros
        filtros = Filtros(
            tecnico_id=self.tecnico.currentData(),
            turno=base.turno,
            prioridades=(self.prioridad.currentData(),) if self.prioridad.currentData() else (),
            estados=(self.estado_ticket.currentData(),) if self.estado_ticket.currentData() else (),
        )
        try:
            datos = novedades.listar(
                self.estado.conexion, self.estado.sesion, self.estado.periodo, self.acceso.currentData(), filtros
            )
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.tabla.fijar_datos(datos)

    def abrir_detalle(self, id_glpi: int) -> None:
        try:
            detalle = novedades.detalle(self.estado.conexion, self.estado.sesion, id_glpi)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        DialogoDetalleTicket(detalle, self, self.estado).exec()


def _tabla(encabezados: list[str], filas: list[list]) -> QTableWidget:
    tabla = QTableWidget(len(filas), len(encabezados))
    tabla.setHorizontalHeaderLabels(encabezados)
    tabla.verticalHeader().setVisible(False)
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    for i, fila in enumerate(filas):
        for j, valor in enumerate(fila):
            tabla.setItem(i, j, QTableWidgetItem("" if valor is None else str(valor)))
    return tabla


class DialogoDetalleTicket(QDialog):
    """PAN-05: datos, cambios detectados y línea de tiempo de eventos."""

    def __init__(self, detalle: novedades.DetalleTicket, padre=None, estado=None):
        super().__init__(padre)
        t = detalle.ticket
        self.setWindowTitle(f"Ticket {t['id_glpi']}")
        self.resize(900, 680)
        datos = QGroupBox("Datos del ticket")
        formulario = QFormLayout(datos)
        horas = t["horas_resolucion"]
        filas = (
            ("ID", t["id_glpi"]), ("Título", t["titulo"]), ("Estado", t["estado"]),
            ("Prioridad", f"{t['prioridad']}{' · P1' if t['es_p1'] else ''}"),
            ("Técnicos", ", ".join(detalle.tecnicos) or "Sin asignar"),
            ("Tipo de caso", NOMBRE_TIPO_CASO[t["tipo_caso"]] + (" (corregido)" if t["tipo_caso_origen"] == "MANUAL" else "")),
            ("Apertura", t["fecha_apertura"][:16]), ("Turno de apertura", t["turno_apertura"]),
            ("Última actualización", t["ultima_actualizacion"][:16]),
            ("Solución (aprox.)", (t["fecha_solucion"] or "—")[:16]),
            ("Cierre (aprox.)", (t["fecha_cierre"] or "—")[:16]),
            ("Horas de resolución (aprox.)", f"{horas:g}" if horas is not None else "—"),
            ("Autor", t["autor"] or "—"), ("Entidad", t["entidad"] or "—"), ("Ubicación", t["ubicacion"] or "—"),
        )
        for etiqueta, valor in filas:
            texto = QLabel(str(valor))
            texto.setWordWrap(True)
            formulario.addRow(f"{etiqueta}:", texto)

        pestanas = QTabWidget()
        pestanas.addTab(_tabla(
            ["Fecha", "Evento", "Técnico", "Origen"],
            [[e["fecha_evento"][:16], NOMBRE_EVENTO[e["tipo"]], e["tecnico"] or "—", NOMBRE_ORIGEN[e["origen"]]]
             for e in detalle.eventos],
        ), "Eventos detectados")
        pestanas.addTab(_tabla(
            ["Detectado", "Campo", "Antes", "Después", "Archivo"],
            [[c["detectado_en"][:16], c["campo"], c["valor_anterior"], c["valor_nuevo"], c["archivo"]]
             for c in detalle.cambios],
        ), "Cambios entre importaciones")
        pestanas.addTab(_seguimientos(detalle.seguimientos), f"Seguimientos ({len(detalle.seguimientos)})")
        pestanas.addTab(_evaluacion(detalle.evaluacion), "Calidad")
        evaluar = QPushButton("Evaluar calidad")
        puede = estado is not None and estado.sesion.es_coordinador
        evaluar.setEnabled(puede)
        evaluar.setToolTip("" if puede else "Solo el coordinador evalúa la calidad.")
        evaluar.clicked.connect(lambda: self._evaluar(estado, t["id_glpi"]))
        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.accept)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(evaluar)
        botones.addWidget(cerrar)
        diseno = QVBoxLayout(self)
        diseno.addWidget(datos)
        diseno.addWidget(pestanas, 1)
        diseno.addLayout(botones)

    def _evaluar(self, estado, ticket_id: int) -> None:
        DialogoEvaluacion(estado, ticket_id, self).exec()


def _seguimientos(notas: list[dict]) -> QWidget:
    texto = QTextBrowser()
    if not notas:
        texto.setHtml("<i>No hay seguimientos importados para este ticket.</i>")
        return texto
    partes = []
    for n in notas:
        etiqueta = (f"<span style='background:#1F3A5F;color:white;padding:0 4px'>[{n['etiqueta']}]</span> "
                    if n["etiqueta"] else "")
        contenido = html.escape(n["contenido"]).replace("\n", "<br>")
        partes.append(f"<p><b>{n['fecha'][:16]}</b> · {n['tipo'].capitalize()} · {html.escape(n['autor'] or '')}<br>"
                      f"{etiqueta}{contenido}</p>")
    texto.setHtml("<hr>".join(partes))
    return texto


def _evaluacion(evaluacion) -> QWidget:
    if evaluacion is None:
        etiqueta = QLabel("Sin evaluación de calidad.")
        etiqueta.setObjectName("nota")
        return etiqueta
    cabecera, detalle = evaluacion
    contenedor = QWidget()
    diseno = QVBoxLayout(contenedor)
    diseno.addWidget(QLabel(
        f"Versión {cabecera['version']} · {cabecera['fecha'][:16]} · {cabecera['auditor'] or '—'} · "
        f"{NOMBRE_TIPO_CASO[cabecera['tipo_caso']]} · {cabecera['porcentaje']} % · "
        f"{calidad.NOMBRE_RESULTADO[cabecera['resultado']]} · críticos fallidos: {cabecera['criticos_fallidos']}"))
    if cabecera["retroalimentacion"]:
        retro = QLabel(f"Retroalimentación: {cabecera['retroalimentacion']}")
        retro.setWordWrap(True)
        diseno.addWidget(retro)
    textos = {calidad.CUMPLE: "✔ Cumple", calidad.NO_CUMPLE: "✖ No cumple", calidad.NO_APLICA: "— No aplica"}
    diseno.addWidget(_tabla(
        ["Criterio", "Descripción", "Resultado", "Origen", "Nota"],
        [[f["criterio_id"] + (" (CRÍTICO)" if f["critico"] else ""), f["descripcion"], textos[f["resultado"]],
          f["origen"], f["nota"]] for f in detalle],
    ))
    return contenedor