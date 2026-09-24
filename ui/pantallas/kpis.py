"""PAN-11: KPIs. Lista de KPIs y editor visual (KPI-00) con vista previa del valor.

Los filtros se arman con listas desplegables; nunca se escribe código. Los KPIs
predefinidos solo permiten cambiar umbrales, meta, visibilidad y marca de crítico.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import configuracion as cfg
from core.analisis import condiciones, semaforo, snapshot
from core.analisis.kpis import CAMPOS_TIEMPO, TIPOS_CALCULO, TIPOS_TIEMPO, CalculadoraKPI
from core.errores import ErrorAplicacion
from core.reportes import graficos
from core.reportes.catalogo import formatear_valor
from ui.componentes.graficos import Grafico
from ui.dialogos import confirmar, mostrar_error, mostrar_info
from ui.hilos import con_conexion, ejecutar

DIRECCIONES = {"MAYOR_MEJOR": "Mayor es mejor", "MENOR_MEJOR": "Menor es mejor", "INFORMATIVO": "Informativo"}


def _numero(texto: str) -> float | None:
    texto = texto.strip().replace(",", ".")
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        raise ErrorAplicacion(f"«{texto}» no es un número.") from None


class DialogoCondicion(QDialog):
    """Elegir un campo y su valor según el tipo del campo."""

    def __init__(self, opciones: dict, padre=None):
        super().__init__(padre)
        self.setWindowTitle("Agregar condición")
        self.opciones = opciones
        self.campo = QComboBox()
        for campo in condiciones.CAMPOS_FILTRO:
            self.campo.addItem(campo.etiqueta, campo.clave)
        self.valores = QListWidget()
        self.booleano = QComboBox()
        self.booleano.addItem("Sí", True)
        self.booleano.addItem("No", False)
        self.minimo = QLineEdit(placeholderText="mínimo (opcional)")
        self.maximo = QLineEdit(placeholderText="máximo (opcional)")
        self.prefijo = QLineEdit(placeholderText="por ejemplo REC o REC-03")
        formulario = QFormLayout(self)
        formulario.addRow("Campo:", self.campo)
        formulario.addRow("Valores:", self.valores)
        formulario.addRow("Valor:", self.booleano)
        formulario.addRow("Desde:", self.minimo)
        formulario.addRow("Hasta:", self.maximo)
        formulario.addRow("Prefijo:", self.prefijo)
        self.formulario = formulario
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        formulario.addRow(botones)
        self.campo.currentIndexChanged.connect(self._mostrar_campos)
        self._mostrar_campos()
        self.condicion: dict | None = None

    def _mostrar_campos(self) -> None:
        campo = condiciones.CAMPOS_POR_CLAVE[self.campo.currentData()]
        visibles = {
            condiciones.LISTA: (self.valores,), condiciones.BOOLEANO: (self.booleano,),
            condiciones.RANGO: (self.minimo, self.maximo), condiciones.PREFIJO: (self.prefijo,),
        }[campo.tipo]
        for widget in (self.valores, self.booleano, self.minimo, self.maximo, self.prefijo):
            self.formulario.setRowVisible(widget, widget in visibles)
        if campo.tipo == condiciones.LISTA:
            self.valores.clear()
            for valor, texto in self.opciones.get(campo.clave, []):
                item = QListWidgetItem(str(texto))
                item.setData(Qt.ItemDataRole.UserRole, valor)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.valores.addItem(item)

    def _aceptar(self) -> None:
        clave = self.campo.currentData()
        tipo = condiciones.CAMPOS_POR_CLAVE[clave].tipo
        try:
            if tipo == condiciones.LISTA:
                elegidos = [self.valores.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.valores.count())
                            if self.valores.item(i).checkState() == Qt.CheckState.Checked]
                condicion = {"campo": clave, "valores": elegidos}
            elif tipo == condiciones.BOOLEANO:
                condicion = {"campo": clave, "valor": self.booleano.currentData()}
            elif tipo == condiciones.RANGO:
                condicion = {"campo": clave}
                for limite, texto in (("min", self.minimo.text()), ("max", self.maximo.text())):
                    if (valor := _numero(texto)) is not None:
                        condicion[limite] = valor
            else:
                condicion = {"campo": clave, "valor": self.prefijo.text()}
            condiciones.validar([condicion])
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.condicion = condicion
        self.accept()


class ListaCondiciones(QGroupBox):
    def __init__(self, titulo: str, pantalla, padre=None):
        super().__init__(titulo, padre)
        self.pantalla = pantalla
        self.lista = QListWidget()
        agregar = QPushButton("Agregar condición…")
        quitar = QPushButton("Quitar")
        quitar.setObjectName("secundario")
        agregar.clicked.connect(self._agregar)
        quitar.clicked.connect(lambda: self.lista.takeItem(self.lista.currentRow()))
        botones = QHBoxLayout()
        botones.addWidget(agregar)
        botones.addWidget(quitar)
        botones.addStretch()
        diseno = QVBoxLayout(self)
        diseno.addWidget(self.lista)
        diseno.addLayout(botones)
        self.setMaximumHeight(170)

    def fijar(self, lista: list[dict]) -> None:
        self.lista.clear()
        for condicion in lista:
            self._poner(condicion)

    def _poner(self, condicion: dict) -> None:
        nombres = {clave: dict(valores) for clave, valores in self.pantalla.opciones.items()}
        item = QListWidgetItem(condiciones.describir([condicion], nombres))
        item.setData(Qt.ItemDataRole.UserRole, condicion)
        self.lista.addItem(item)

    def _agregar(self) -> None:
        dialogo = DialogoCondicion(self.pantalla.opciones, self)
        if dialogo.exec() == QDialog.DialogCode.Accepted and dialogo.condicion:
            self._poner(dialogo.condicion)

    def valor(self) -> list[dict]:
        return [self.lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lista.count())]


class PantallaKPIs(QWidget):
    titulo = "KPIs"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.opciones: dict = {}
        self.codigo: str | None = None
        self.predefinido = False

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Código", "Nombre", "Visible", "Origen"])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        encabezado = self.tabla.horizontalHeader()
        encabezado.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        encabezado.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabla.itemSelectionChanged.connect(self._elegido)
        nuevo = QPushButton("Nuevo KPI")
        nuevo.clicked.connect(self.nuevo)
        generar = QPushButton("Generar snapshot del período")
        generar.setObjectName("secundario")
        generar.setToolTip("Guarda el valor de todos los KPIs del mes o semana elegidos, para las tendencias.")
        generar.clicked.connect(self.generar_snapshot)
        botones_izq = QHBoxLayout()
        botones_izq.addWidget(nuevo)
        botones_izq.addWidget(generar)
        self.grafico_tendencia = Grafico()
        izquierda = QWidget()
        diseno_izq = QVBoxLayout(izquierda)
        diseno_izq.addWidget(self.tabla)
        diseno_izq.addLayout(botones_izq)
        diseno_izq.addWidget(self.grafico_tendencia)

        self.nombre = QLineEdit()
        self.descripcion = QLineEdit()
        self.tipo = QComboBox()
        for clave, texto in TIPOS_CALCULO.items():
            self.tipo.addItem(texto, clave)
        self.campo_tiempo = QComboBox()
        for clave, texto in CAMPOS_TIEMPO.items():
            self.campo_tiempo.addItem(texto, clave)
        self.direccion = QComboBox()
        for clave, texto in DIRECCIONES.items():
            self.direccion.addItem(texto, clave)
        self.verde, self.amarillo, self.meta = QLineEdit(), QLineEdit(), QLineEdit()
        self.visible = QCheckBox("Visible en el dashboard")
        self.critico = QCheckBox("Crítico (cuenta para la criticidad global)")
        formulario = QFormLayout()
        formulario.addRow("Nombre:", self.nombre)
        formulario.addRow("Descripción:", self.descripcion)
        formulario.addRow("Tipo de cálculo:", self.tipo)
        formulario.addRow("Campo de tiempo:", self.campo_tiempo)
        formulario.addRow("Semáforo:", self.direccion)
        umbrales = QHBoxLayout()
        for texto, campo in (("Verde", self.verde), ("Amarillo", self.amarillo), ("Meta", self.meta)):
            umbrales.addWidget(QLabel(texto))
            umbrales.addWidget(campo)
        formulario.addRow("Umbrales:", umbrales)
        formulario.addRow("", self.visible)
        formulario.addRow("", self.critico)
        self.formulario = formulario
        self.numerador = ListaCondiciones("Condiciones (numerador / tickets que cuentan)", self)
        self.denominador = ListaCondiciones("Denominador (base del porcentaje)", self)
        self.ayuda_universo = QLabel()
        self.ayuda_universo.setObjectName("nota")
        self.ayuda_universo.setWordWrap(True)
        self.previa = QLabel()
        self.previa.setStyleSheet("font-size: 12pt; font-weight: 600;")
        previa = QPushButton("Vista previa")
        previa.setObjectName("secundario")
        previa.clicked.connect(self.vista_previa)
        guardar = QPushButton("Guardar")
        guardar.clicked.connect(self.guardar)
        self.eliminar_boton = QPushButton("Eliminar")
        self.eliminar_boton.setObjectName("secundario")
        self.eliminar_boton.clicked.connect(self.eliminar)
        botones = QHBoxLayout()
        for boton in (previa, guardar, self.eliminar_boton):
            botones.addWidget(boton)
        botones.addWidget(self.previa, 1)
        derecha = QWidget()
        diseno_der = QVBoxLayout(derecha)
        diseno_der.addLayout(formulario)
        diseno_der.addWidget(self.ayuda_universo)
        diseno_der.addWidget(self.numerador)
        diseno_der.addWidget(self.denominador)
        diseno_der.addLayout(botones)
        diseno_der.addStretch()
        self.tipo.currentIndexChanged.connect(self._ajustar_tipo)

        divisor = QSplitter()
        divisor.addWidget(izquierda)
        divisor.addWidget(derecha)
        divisor.setSizes([560, 700])
        QVBoxLayout(self).addWidget(divisor)
        self.nuevo()

    # --- Lista ---

    def actualizar(self) -> None:
        self.opciones = condiciones.opciones(self.estado.conexion, [f.turno for f in self.estado.config.turnos])
        filas = cfg.listar_kpis(self.estado.conexion)
        self.tabla.setRowCount(len(filas))
        for i, f in enumerate(filas):
            codigo = QTableWidgetItem(f["codigo"])
            codigo.setData(Qt.ItemDataRole.UserRole, dict(f))
            self.tabla.setItem(i, 0, codigo)
            self.tabla.setItem(i, 1, QTableWidgetItem(f["nombre"]))
            self.tabla.setItem(i, 2, QTableWidgetItem("Sí" if f["visible_dashboard"] else "No"))
            self.tabla.setItem(i, 3, QTableWidgetItem("Predefinido" if f["predefinido"] else "Usuario"))

    def _elegido(self) -> None:
        filas = self.tabla.selectionModel().selectedRows()
        if filas:
            self._cargar(self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole))

    # --- Editor ---

    def nuevo(self) -> None:
        self._cargar({"codigo": None, "nombre": "", "descripcion": "", "tipo_calculo": "PORCENTAJE",
                      "campo_tiempo": None, "direccion": "MENOR_MEJOR", "umbral_verde": None,
                      "umbral_amarillo": None, "meta": None, "visible_dashboard": 1, "critico": 0,
                      "predefinido": 0, "filtro_numerador_json": None, "filtro_denominador_json": None})
        self.tabla.clearSelection()

    def _cargar(self, fila: dict) -> None:
        self.codigo = fila["codigo"]
        self.predefinido = bool(fila["predefinido"])
        texto = lambda v: "" if v is None else f"{v:g}"  # noqa: E731
        self.nombre.setText(fila["nombre"])
        self.descripcion.setText(fila["descripcion"] or "")
        self.tipo.setCurrentIndex(max(0, self.tipo.findData(fila["tipo_calculo"])))
        self.campo_tiempo.setCurrentIndex(max(0, self.campo_tiempo.findData(fila["campo_tiempo"])))
        self.direccion.setCurrentIndex(max(0, self.direccion.findData(fila["direccion"])))
        self.verde.setText(texto(fila["umbral_verde"]))
        self.amarillo.setText(texto(fila["umbral_amarillo"]))
        self.meta.setText(texto(fila["meta"]))
        self.visible.setChecked(bool(fila["visible_dashboard"]))
        self.critico.setChecked(bool(fila["critico"]))
        self.numerador.fijar(condiciones.leer(fila["filtro_numerador_json"]))
        self.denominador.fijar(condiciones.leer(fila["filtro_denominador_json"]))
        for widget in (self.nombre, self.descripcion, self.tipo, self.campo_tiempo, self.direccion,
                       self.numerador, self.denominador):
            widget.setEnabled(not self.predefinido)
        self.eliminar_boton.setEnabled(self.codigo is not None and not self.predefinido)
        self.previa.clear()
        self._ajustar_tipo()
        if self.codigo:
            puntos = snapshot.tendencia(self.estado.conexion, self.codigo, cantidad=12)
            self.grafico_tendencia.mostrar(graficos.tendencia(puntos, f"Tendencia 12 meses · {self.codigo}",
                                                              fila.get("unidad") or ""))

    def _ajustar_tipo(self) -> None:
        tipo = self.tipo.currentData()
        self.formulario.setRowVisible(self.campo_tiempo, tipo in TIPOS_TIEMPO)
        self.denominador.setVisible(tipo == "PORCENTAJE" and not self.predefinido)
        self.numerador.setVisible(not self.predefinido)
        if self.predefinido:
            self.ayuda_universo.setText("KPI predefinido: su fórmula es fija (ver especificación 05). "
                                        "Puede cambiar umbrales, meta, visibilidad y marca de crítico.")
        elif tipo in TIPOS_TIEMPO:
            self.ayuda_universo.setText("Se calcula sobre los tickets resueltos en el período que cumplen las condiciones.")
        else:
            self.ayuda_universo.setText("Se calcula sobre los tickets recibidos en el período. En un porcentaje, "
                                        "el numerador cumple además las condiciones del denominador.")

    def _datos(self) -> dict:
        return {
            "nombre": self.nombre.text(), "descripcion": self.descripcion.text(),
            "tipo_calculo": self.tipo.currentData(), "campo_tiempo": self.campo_tiempo.currentData(),
            "direccion": self.direccion.currentData(), "umbral_verde": _numero(self.verde.text()),
            "umbral_amarillo": _numero(self.amarillo.text()), "meta": _numero(self.meta.text()),
            "visible_dashboard": self.visible.isChecked(), "critico": self.critico.isChecked(),
            "numerador": self.numerador.valor(), "denominador": self.denominador.valor(),
        }

    def vista_previa(self) -> None:
        calc = CalculadoraKPI(self.estado.conexion, self.estado.sesion)
        try:
            if self.predefinido:
                resultado = calc.calcular(self.codigo, self.estado.periodo, self.estado.filtros, comparar=False)
            else:
                definicion = cfg.definicion_kpi(self._datos(), self.codigo or "KPI-NUEVO")
                resultado = calc.calcular_definicion(definicion, self.estado.periodo, self.estado.filtros, False)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.previa.setText(f"{self.estado.periodo.etiqueta}: {formatear_valor(resultado, resultado.valor)} · "
                            f"{semaforo.etiqueta(resultado.semaforo)} (base {resultado.cantidad})")

    def guardar(self) -> None:
        try:
            datos = self._datos()
            if self.predefinido:
                cfg.actualizar_kpi(self.estado.conexion, self.estado.sesion, self.codigo, {
                    c: datos[c] for c in ("umbral_verde", "umbral_amarillo", "meta", "visible_dashboard", "critico")
                })
            else:
                self.codigo = cfg.guardar_kpi_personalizado(self.estado.conexion, self.estado.sesion, datos, self.codigo)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.estado.datos_cambiados.emit()
        self.actualizar()
        mostrar_info(f"KPI {self.codigo} guardado. El cambio quedó en el historial.", self)

    def generar_snapshot(self) -> None:
        periodo, estado = self.estado.periodo, self.estado
        if periodo.granularidad not in snapshot.GRANULARIDAD:
            mostrar_error("El snapshot se genera por mes o por semana: elija uno de esos períodos arriba.", self)
            return
        ejecutar(self, con_conexion(estado, lambda conexion, avance: snapshot.generar(
            conexion, periodo, estado.sesion.usuario_id)),
            lambda cantidad: (mostrar_info(f"Snapshot de {periodo.etiqueta}: {cantidad} valores guardados.", self),
                              self._elegido()),
            lambda mensaje: mostrar_error(mensaje, self))

    def eliminar(self) -> None:
        if not self.codigo or not confirmar(f"¿Eliminar el KPI {self.codigo}?", self):
            return
        try:
            cfg.eliminar_kpi_personalizado(self.estado.conexion, self.estado.sesion, self.codigo)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.estado.datos_cambiados.emit()
        self.actualizar()
        self.nuevo()

