"""PAN-10: Calidad de soporte (spec 07).

Pestañas: (1) Evaluar tickets con casillas tri-estado (CAL-01 a CAL-04, solo coordinador);
(2) Histórico por técnico semana a semana (CAL-05); (3) Rendimiento (CAL-06);
(4) Panel comparativo y ranking, solo coordinador (CAL-07); (5) Incumplimiento por
criterio (CAL-08). Un usuario de consulta ve solo sus propios datos.
"""

import html

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QScrollArea, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from core import reloj
from core.analisis import calidad as cal
from core.analisis import calidad_metricas as met
from core.analisis import periodos, responsables
from core.dominio import NOMBRE_TIPO_CASO, TIPOS_CASO
from core.errores import ErrorAplicacion
from core.importacion import seguimientos as seg
from core.reportes import graficos
from ui.componentes.graficos import Grafico
from ui.componentes.tabla import TablaDatos
from ui.componentes.tri_estado import CasillaTriEstado
from ui.dialogos import mostrar_error, mostrar_info

COLOR_RESULTADO = {cal.CONFORME: "#2E7D32", cal.POR_MEJORAR: "#F9A825", cal.NO_CONFORME: "#C62828"}


# --- Panel de evaluación (CAL-01, CAL-02, CAL-03) ---

class FilaCriterio(QWidget):
    def __init__(self, criterio, precalificacion: cal.Precalificacion | None, al_cambiar, padre=None):
        super().__init__(padre)
        self.criterio = criterio["id"]
        self.automatico = precalificacion
        self.casilla = CasillaTriEstado(precalificacion.resultado if precalificacion else None)
        self.casilla.cambiado.connect(lambda _: (self._actualizar_nota(), al_cambiar()))
        texto = QLabel(f"<b>{criterio['id']}</b> {html.escape(criterio['descripcion'])}")
        texto.setWordWrap(True)
        texto.setToolTip(f"Cómo verificar: {criterio['como_verificar'] or '—'}\nRegla: {criterio['regla'] or '—'}")
        etiquetas = QHBoxLayout()
        if criterio["critico"]:
            critico = QLabel("CRÍTICO")
            critico.setStyleSheet("color: white; background: #C62828; border-radius: 3px; padding: 1px 5px; font-weight: 600;")
            etiquetas.addWidget(critico)
        if precalificacion:
            auto = QLabel("AUTO")
            auto.setStyleSheet("color: white; background: #1F3A5F; border-radius: 3px; padding: 1px 5px;")
            auto.setToolTip(f"Precalificado: {precalificacion.nota}")
            etiquetas.addWidget(auto)
        etiquetas.addStretch()
        self.nota = QLineEdit(placeholderText="Nota (obligatoria si corrige un resultado AUTO)")
        izquierda = QVBoxLayout()
        izquierda.addWidget(texto)
        izquierda.addLayout(etiquetas)
        izquierda.addWidget(self.nota)
        diseno = QHBoxLayout(self)
        diseno.setContentsMargins(4, 4, 4, 4)
        diseno.addWidget(self.casilla, alignment=Qt.AlignmentFlag.AlignTop)
        diseno.addLayout(izquierda, 1)
        self._actualizar_nota()

    def _actualizar_nota(self) -> None:
        corregido = self.automatico is not None and self.casilla.valor != self.automatico.resultado
        self.nota.setStyleSheet("border: 1px solid #C62828;" if corregido and not self.nota.text().strip() else "")

    def resultado(self) -> tuple[str | None, str]:
        return self.casilla.valor, self.nota.text()


class PanelEvaluacion(QWidget):
    """Evaluación de un ticket: tipo de caso, criterios que aplican, puntaje en vivo,
    retroalimentación y seguimientos del ticket al lado."""

    def __init__(self, estado, al_guardar=None, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.al_guardar = al_guardar
        self.ticket_id: int | None = None
        self.filas: list[FilaCriterio] = []
        self.cabecera = QLabel("Elija un ticket para evaluar.")
        self.cabecera.setWordWrap(True)
        self.cabecera.setStyleSheet("font-weight: 600;")
        self.tipo = QComboBox()
        for codigo in TIPOS_CASO:
            self.tipo.addItem(NOMBRE_TIPO_CASO[codigo], codigo)
        self.tipo.activated.connect(self._cargar_criterios)
        self.puntaje = QLabel()
        self.puntaje.setStyleSheet("font-size: 12pt; font-weight: 600;")
        self.lista = QWidget()
        self.lista_diseno = QVBoxLayout(self.lista)
        self.lista_diseno.addStretch()
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setWidget(self.lista)
        self.retro = QPlainTextEdit()
        self.retro.setPlaceholderText("Retroalimentación para el técnico")
        self.retro.setMaximumHeight(80)
        self.guardar_boton = QPushButton("Guardar evaluación")
        self.guardar_boton.clicked.connect(self.guardar)
        self.guardar_boton.setEnabled(False)
        centro = QWidget()
        diseno_centro = QVBoxLayout(centro)
        fila_tipo = QHBoxLayout()
        fila_tipo.addWidget(QLabel("Tipo de caso:"))
        fila_tipo.addWidget(self.tipo)
        fila_tipo.addStretch()
        fila_tipo.addWidget(self.puntaje)
        diseno_centro.addWidget(self.cabecera)
        diseno_centro.addLayout(fila_tipo)
        diseno_centro.addWidget(desplazable, 1)
        diseno_centro.addWidget(self.retro)
        diseno_centro.addWidget(self.guardar_boton, alignment=Qt.AlignmentFlag.AlignRight)
        self.notas = QTextBrowser()
        caja_notas = QGroupBox("Seguimientos del ticket")
        QVBoxLayout(caja_notas).addWidget(self.notas)
        divisor = QSplitter()
        divisor.addWidget(centro)
        divisor.addWidget(caja_notas)
        divisor.setSizes([640, 420])
        QVBoxLayout(self).addWidget(divisor)

    def cargar(self, ticket_id: int) -> None:
        conexion = self.estado.conexion
        ticket = conexion.execute(
            "SELECT t.*, k.nombre_mostrar AS tecnico FROM ticket t LEFT JOIN tecnico k ON k.id = t.tecnico_principal_id "
            "WHERE t.id_glpi = ?", (ticket_id,)).fetchone()
        if ticket is None:
            mostrar_error(f"El ticket {ticket_id} no existe.", self)
            return
        self.ticket_id = ticket_id
        vigente = cal.evaluacion_vigente(conexion, self.estado.sesion, ticket_id)
        previa = (f" · Evaluación vigente: v{vigente[0]['version']} {vigente[0]['porcentaje']}% "
                  f"{cal.NOMBRE_RESULTADO[vigente[0]['resultado']]}") if vigente else ""
        self.cabecera.setText(f"Ticket {ticket_id}: {ticket['titulo']} · {ticket['prioridad']} · {ticket['estado']} · "
                              f"{ticket['tecnico'] or 'Sin técnico'}{previa}")
        tipo = vigente[0]["tipo_caso"] if vigente else cal.tipo_caso_sugerido(conexion, ticket_id)
        self.tipo.setCurrentIndex(self.tipo.findData(tipo))
        self.retro.setPlainText(vigente[0]["retroalimentacion"] or "" if vigente else "")
        self._mostrar_notas(ticket_id)
        self._cargar_criterios(anteriores={f["criterio_id"]: f for f in vigente[1]} if vigente else {})
        self.guardar_boton.setEnabled(True)

    def _mostrar_notas(self, ticket_id: int) -> None:
        notas = seg.de_ticket(self.estado.conexion, ticket_id)
        if not notas:
            self.notas.setHtml("<i>No hay seguimientos importados para este ticket. Los criterios que dependen de "
                               "las notas se califican a mano.</i>")
            return
        partes = []
        for n in notas:
            etiqueta = f"<span style='background:#1F3A5F;color:white;padding:0 4px'>[{n['etiqueta']}]</span> " \
                if n["etiqueta"] else ""
            contenido = html.escape(n["contenido"]).replace("\n", "<br>")
            if n["etiqueta"]:
                contenido = contenido.replace(f"[{n['etiqueta']}]", "", 1)
            partes.append(f"<p><b>{n['fecha'][:16]}</b> · {n['tipo'].capitalize()} · {html.escape(n['autor'] or '')}"
                          f"{' · privado' if n['privado'] else ''}<br>{etiqueta}{contenido}</p>")
        self.notas.setHtml("<hr>".join(partes))

    def _cargar_criterios(self, *_, anteriores: dict | None = None) -> None:
        if self.ticket_id is None:
            return
        while self.lista_diseno.count() > 1:
            self.lista_diseno.takeAt(0).widget().deleteLater()
        tipo = self.tipo.currentData()
        automaticos = cal.precalificar(self.estado.conexion, self.ticket_id, tipo)
        self.filas = []
        for criterio in cal.criterios_para(self.estado.conexion, tipo):
            fila = FilaCriterio(criterio, automaticos.get(criterio["id"]), self._recalcular)
            anterior = (anteriores or {}).get(criterio["id"])
            if anterior is not None:
                fila.casilla.fijar(anterior["resultado"])
                if anterior["origen"] != cal.AUTO:
                    fila.nota.setText(anterior["nota"] or "")
            self.filas.append(fila)
            self.lista_diseno.insertWidget(self.lista_diseno.count() - 1, fila)
        self._recalcular()

    def _recalcular(self) -> None:
        """Puntaje en vivo (CAL-03)."""
        marcados = {f.criterio: f.casilla.valor for f in self.filas if f.casilla.valor}
        pendientes = len(self.filas) - len(marcados)
        puntaje = cal.puntaje_con_parametros(self.estado.conexion, marcados)
        porcentaje = "—" if puntaje.porcentaje is None else f"{puntaje.porcentaje:g} %"
        color = COLOR_RESULTADO[puntaje.resultado]
        self.puntaje.setText(f"{porcentaje} · críticos fallidos: {puntaje.criticos_fallidos} · "
                             f"{cal.NOMBRE_RESULTADO[puntaje.resultado]}" + (f" · {pendientes} sin marcar" if pendientes else ""))
        self.puntaje.setStyleSheet(f"font-size: 12pt; font-weight: 600; color: {color};")

    def guardar(self) -> None:
        if self.ticket_id is None:
            return
        resultados = {f.criterio: f.resultado() for f in self.filas}
        sin_marcar = [c for c, (v, _) in resultados.items() if v is None]
        if sin_marcar:
            mostrar_error(f"Marque todos los criterios. Faltan: {', '.join(sin_marcar)}.", self)
            return
        try:
            cal.guardar_evaluacion(self.estado.conexion, self.estado.sesion, self.ticket_id, self.tipo.currentData(),
                                   resultados, self.retro.toPlainText())
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.estado.datos_cambiados.emit()
        mostrar_info("Evaluación guardada. Quedó en el historial.", self)
        if self.al_guardar:
            self.al_guardar()
        self.cargar(self.ticket_id)


class DialogoEvaluacion(QDialog):
    def __init__(self, estado, ticket_id: int, padre=None):
        super().__init__(padre)
        self.setWindowTitle(f"Evaluar calidad · ticket {ticket_id}")
        self.resize(1200, 760)
        self.panel = PanelEvaluacion(estado, padre=self)
        QVBoxLayout(self).addWidget(self.panel)
        self.panel.cargar(ticket_id)


# --- Pantalla ---

class PantallaCalidad(QWidget):
    titulo = "Calidad"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        coordinador = estado.sesion.es_coordinador
        self.pestanas = QTabWidget()
        if coordinador:
            self.pestanas.addTab(self._crear_evaluar(), "Evaluar tickets")
        self.pestanas.addTab(self._crear_historico(), "Histórico por técnico")
        self.pestanas.addTab(self._crear_rendimiento(), "Rendimiento")
        if coordinador:
            self.pestanas.addTab(self._crear_ranking(), "Comparativo y ranking")
        self.pestanas.addTab(self._crear_incumplimiento(), "Incumplimiento por criterio")
        self.pestanas.currentChanged.connect(lambda _: self._actualizar_pestana())
        QVBoxLayout(self).addWidget(self.pestanas)

    def actualizar(self) -> None:
        self._cargar_tecnicos()
        self._actualizar_pestana()

    def _actualizar_pestana(self) -> None:
        widget = self.pestanas.currentWidget()
        try:
            getattr(widget, "refrescar", lambda: None)()
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)

    # (1) Evaluar
    def _crear_evaluar(self) -> QWidget:
        pagina = QWidget()
        self.semana = QComboBox()
        actual = periodos.semana_de(reloj.ahora()).anterior()
        for semana in reversed(periodos.ultimos(actual, 8)):
            self.semana.addItem(semana.etiqueta, semana)
        self.semana.activated.connect(lambda _: self._cargar_muestra())
        self.muestra = TablaDatos(self.estado, "Muestra semanal", columnas_personales=("Técnico",))
        self.muestra.fila_activada.connect(lambda fila: self.panel.cargar(int(fila["ID"])))
        self.muestra.vista.clicked.connect(
            lambda i: self.panel.cargar(int(self.muestra.modelo.fila(self.muestra.filtro.mapToSource(i).row())["ID"])))
        self.buscar_id = QLineEdit(placeholderText="ID de ticket")
        buscar = QPushButton("Evaluar")
        buscar.clicked.connect(self._evaluar_id)
        agregar = QPushButton("Agregar a la muestra")
        agregar.setObjectName("secundario")
        agregar.clicked.connect(self._agregar)
        quitar = QPushButton("Quitar de la muestra")
        quitar.setObjectName("secundario")
        quitar.clicked.connect(self._quitar)
        controles = QGridLayout()
        controles.addWidget(QLabel("Semana:"), 0, 0)
        controles.addWidget(self.semana, 0, 1, 1, 2)
        controles.addWidget(self.buscar_id, 1, 0, 1, 2)
        controles.addWidget(buscar, 1, 2)
        controles.addWidget(agregar, 2, 0, 1, 2)
        controles.addWidget(quitar, 2, 2)
        izquierda = QWidget()
        diseno_izq = QVBoxLayout(izquierda)
        nota = QLabel("Muestra sugerida (CAL-04): todos los P1, los escalados largos, al menos uno por técnico cada 2 "
                      "semanas y el resto al azar.")
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        diseno_izq.addWidget(nota)
        diseno_izq.addLayout(controles)
        diseno_izq.addWidget(self.muestra)
        self.panel = PanelEvaluacion(self.estado, al_guardar=self._cargar_muestra)
        divisor = QSplitter()
        divisor.addWidget(izquierda)
        divisor.addWidget(self.panel)
        divisor.setSizes([380, 1000])
        QVBoxLayout(pagina).addWidget(divisor)
        pagina.refrescar = self._cargar_muestra
        return pagina

    def _cargar_muestra(self) -> None:
        semana = self.semana.currentData()
        self.muestra.fijar_datos(met.muestra_de_semana(self.estado.conexion, self.estado.sesion, semana))

    def _evaluar_id(self) -> None:
        texto = self.buscar_id.text().replace(" ", "")
        if texto.isdigit():
            self.panel.cargar(int(texto))

    def _agregar(self) -> None:
        texto = self.buscar_id.text().replace(" ", "")
        if not texto.isdigit():
            mostrar_error("Escriba el ID del ticket que quiere agregar.", self)
            return
        try:
            met.agregar_a_muestra(self.estado.conexion, self.estado.sesion, self.semana.currentData(), int(texto))
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self._cargar_muestra()

    def _quitar(self) -> None:
        filas = self.muestra.filas_seleccionadas()
        if filas:
            met.quitar_de_muestra(self.estado.conexion, self.estado.sesion, self.semana.currentData(), int(filas[0]["ID"]))
            self._cargar_muestra()

    # (2) Histórico
    def _crear_historico(self) -> QWidget:
        pagina = QWidget()
        self.tecnico = QComboBox()
        self.tecnico.activated.connect(lambda _: self._cargar_historico())
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Técnico:"))
        fila.addWidget(self.tecnico)
        self.turno = QLabel()
        self.turno.setObjectName("nota")
        fila.addWidget(self.turno)
        fila.addStretch()
        self.historico = TablaDatos(self.estado, "Histórico semanal")
        self.grafico_historico = Grafico()
        diseno = QVBoxLayout(pagina)
        diseno.addLayout(fila)
        diseno.addWidget(self.historico, 1)
        diseno.addWidget(self.grafico_historico, 1)
        pagina.refrescar = self._cargar_historico
        return pagina

    def _cargar_tecnicos(self) -> None:
        actual = self.tecnico.currentData()
        self.tecnico.clear()
        try:
            for fila in responsables.tecnicos_visibles(self.estado.conexion, self.estado.sesion):
                self.tecnico.addItem(fila["nombre_mostrar"], (fila["id"], fila["turno"]))
        except ErrorAplicacion:
            pass
        if actual is not None:
            indice = self.tecnico.findData(actual)
            self.tecnico.setCurrentIndex(max(0, indice))

    def _cargar_historico(self) -> None:
        if self.tecnico.count() == 0:
            self.historico.fijar_datos(pd.DataFrame())
            return
        tecnico_id, turno = self.tecnico.currentData()
        self.turno.setText(f"Turno: {turno or 'sin asignar'} (la carga varía por turno)")
        tabla = met.historico_semanal(self.estado.conexion, self.estado.sesion, tecnico_id)
        self.historico.fijar_datos(tabla)
        series = tabla.set_index("Semana")[["Atendidos", "% documentación"]].astype(float)
        self.grafico_historico.mostrar(graficos.lineas(series, f"Semana a semana · {self.tecnico.currentText()}"))

    # (3) Rendimiento
    def _crear_rendimiento(self) -> QWidget:
        pagina = QWidget()
        nota = QLabel("Índice de velocidad: mediana de (horas del ticket / mediana del equipo en la misma categoría). "
                      "Menos de 1 = más rápido que el equipo en casos equivalentes. El % de escalados se compara solo "
                      "dentro de cada familia.")
        nota.setObjectName("nota")
        nota.setWordWrap(True)
        self.rendimiento = TablaDatos(self.estado, "Rendimiento")
        self.escalamiento = TablaDatos(self.estado, "Escalamiento por familia")
        diseno = QVBoxLayout(pagina)
        diseno.addWidget(nota)
        diseno.addWidget(self.rendimiento, 2)
        diseno.addWidget(QLabel("% de tickets escalados por familia"))
        diseno.addWidget(self.escalamiento, 1)

        def refrescar():
            tabla = met.rendimiento(self.estado.conexion, self.estado.sesion, self.estado.periodo)
            self.rendimiento.fijar_datos(tabla)
            self.rendimiento.vista.setColumnHidden(list(tabla.columns).index("_id"), True)
            self.escalamiento.fijar_datos(met.escalamiento_por_familia(self.estado.conexion, self.estado.sesion,
                                                                       self.estado.periodo))
        pagina.refrescar = refrescar
        return pagina

    # (4) Ranking
    def _crear_ranking(self) -> QWidget:
        pagina = QWidget()
        aviso = QLabel(met.AVISO_RANKING)
        aviso.setObjectName("aviso")
        self.ranking = TablaDatos(self.estado, "Ranking de técnicos")
        self.ranking.vista.clicked.connect(lambda _: self._mostrar_radar())
        self.radar = Grafico()
        self.radar.setMinimumHeight(320)
        self.tendencia_ranking = TablaDatos(self.estado, "Tendencia del índice (3 meses)")
        self.excluidos = QLabel()
        self.excluidos.setObjectName("nota")
        self.excluidos.setWordWrap(True)
        abajo = QHBoxLayout()
        abajo.addWidget(self.radar, 1)
        caja = QVBoxLayout()
        caja.addWidget(QLabel("Tendencia del índice (3 meses)"))
        caja.addWidget(self.tendencia_ranking)
        caja.addWidget(self.excluidos)
        abajo.addLayout(caja, 1)
        diseno = QVBoxLayout(pagina)
        diseno.addWidget(aviso)
        diseno.addWidget(self.ranking, 1)
        diseno.addLayout(abajo, 1)
        pagina.refrescar = self._cargar_ranking
        return pagina

    def _cargar_ranking(self) -> None:
        self._resultado_ranking = met.ranking(self.estado.conexion, self.estado.sesion, self.estado.periodo)
        r = self._resultado_ranking
        tabla = pd.DataFrame([{
            "Técnico": f.nombre, "Turno": f.turno or "—", "Atendidos": f.atendidos, "Calidad": f.calidad,
            "Velocidad": f.velocidad, "Completitud": f.completitud, "Índice": f.indice, "Evaluaciones": f.evaluaciones,
        } for f in r.filas] + [{"Técnico": "Promedio del equipo", "Calidad": r.promedio.get("calidad"),
                                 "Velocidad": r.promedio.get("velocidad"), "Completitud": r.promedio.get("completitud"),
                                 "Índice": r.promedio.get("indice")}],
            columns=["Técnico", "Turno", "Atendidos", "Calidad", "Velocidad", "Completitud", "Índice", "Evaluaciones"])
        self.ranking.fijar_datos(tabla)
        self.tendencia_ranking.fijar_datos(
            met.tendencia_ranking(self.estado.conexion, self.estado.sesion, self.estado.periodo).reset_index()
            .rename(columns={"index": "Técnico"}))
        self.excluidos.setText("Excluidos: " + ("; ".join(f"{n} ({m})" for n, m in r.excluidos) or "ninguno"))
        self._mostrar_radar()

    def _mostrar_radar(self) -> None:
        r = getattr(self, "_resultado_ranking", None)
        if r is None:
            return
        filas = self.ranking.filas_seleccionadas()
        nombre = filas[0]["Técnico"] if filas else (r.filas[0].nombre if r.filas else None)
        dimensiones = ["Calidad", "Velocidad", "Completitud"]
        series = {"Promedio del equipo": [r.promedio.get("calidad"), r.promedio.get("velocidad"), r.promedio.get("completitud")]}
        elegido = next((f for f in r.filas if f.nombre == nombre), None)
        if elegido:
            series = {elegido.nombre: [elegido.calidad, elegido.velocidad, elegido.completitud]} | series
        self.radar.mostrar(graficos.radar(dimensiones, series, "Dimensiones (0–100)"))

    # (5) Incumplimiento
    def _crear_incumplimiento(self) -> QWidget:
        pagina = QWidget()
        self.incumplimiento = TablaDatos(
            self.estado, "Incumplimiento por criterio",
            color_fila=lambda fila: "#FFF3C4" if fila.get("Capacitación") else None)
        nota = QLabel("Criterios con 30 % o más de «no cumple» se destacan como tema de capacitación "
                      "(parámetro alerta_criterio_porcentaje).")
        nota.setObjectName("nota")
        diseno = QVBoxLayout(pagina)
        diseno.addWidget(nota)
        diseno.addWidget(self.incumplimiento)
        pagina.refrescar = lambda: self.incumplimiento.fijar_datos(
            met.incumplimiento_por_criterio(self.estado.conexion, self.estado.sesion, self.estado.periodo))
        return pagina

