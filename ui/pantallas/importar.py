"""PAN-02: Importar. Archivo → autodetección → mapeo con perfil → vista previa
validada → importar → resumen. Incluye el historial de importaciones.

La validación y la carga corren en hilos de trabajo con barra de progreso (RNF-06).
"""

from pathlib import Path

import pandas as pd
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from core.analisis import hallazgos
from core.analisis.kpis import NOMBRE_PRIORIDAD
from core.analisis.series import NOMBRE_ESTADO
from core.errores import ErrorAplicacion
from core.fuentes.fuente_csv import FORMATOS_FECHA, SEPARADORES, FuenteCSV
from core.importacion import carga, mapeo, validacion
from core.importacion.validacion import ADVERTENCIA, ERROR, VALIDA, formato_legible
from ui.componentes.tabla import TablaDatos
from ui.dialogos import mostrar_error, mostrar_info
from ui.hilos import con_conexion, ejecutar

CODIFICACIONES = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
NOMBRE_SEPARADOR = {";": "Punto y coma (;)", ",": "Coma (,)", "\t": "Tabulador", "|": "Barra (|)"}
SIN_ASIGNAR = "(sin asignar)"
TEXTO_RESULTADO = {VALIDA: "✔ Válida", ADVERTENCIA: "▲ Advertencia", ERROR: "✖ Error"}
COLOR_RESULTADO = {"✔ Válida": "#E8F5E9", "▲ Advertencia": "#FFF8E1", "✖ Error": "#FFEBEE"}


class PantallaImportar(QWidget):
    titulo = "Importar"

    def __init__(self, estado, padre=None):
        super().__init__(padre)
        self.estado = estado
        self.fuente: FuenteCSV | None = None
        self.perfil_base: mapeo.PerfilImportacion | None = None
        self.resultado: validacion.ResultadoValidacion | None = None

        # 1. Archivo
        elegir = QPushButton("Elegir archivo CSV…")
        elegir.clicked.connect(self.elegir_archivo)
        self.ruta = QLabel("Ningún archivo elegido.")
        self.aviso = QLabel()
        self.aviso.setObjectName("aviso")
        self.aviso.setWordWrap(True)
        self.aviso.hide()
        caja_archivo = QGroupBox("1. Archivo exportado de GLPI")
        fila = QHBoxLayout()
        fila.addWidget(elegir)
        fila.addWidget(self.ruta, 1)
        diseno_archivo = QVBoxLayout(caja_archivo)
        diseno_archivo.addLayout(fila)
        diseno_archivo.addWidget(self.aviso)

        # 2. Formato y mapeo
        self.nombre_perfil = QLineEdit()
        self.codificacion = QComboBox()
        self.codificacion.addItems(CODIFICACIONES)
        self.separador = QComboBox()
        for separador in SEPARADORES:
            self.separador.addItem(NOMBRE_SEPARADOR[separador], separador)
        self.formato_fecha = QComboBox()
        for formato in FORMATOS_FECHA:
            self.formato_fecha.addItem(formato_legible(formato), formato)
        self.codificacion.activated.connect(self._reformatear)
        self.separador.activated.connect(self._reformatear)
        self.mapeo = QTableWidget(len(mapeo.CAMPOS_TICKET), 2)
        self.mapeo.setHorizontalHeaderLabels(["Campo del analizador", "Columna del archivo"])
        self.mapeo.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mapeo.verticalHeader().setVisible(False)
        for numero, campo in enumerate(mapeo.CAMPOS_TICKET):
            texto = campo.etiqueta + (" *" if campo.obligatorio else "")
            celda = QTableWidgetItem(texto)
            celda.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.mapeo.setItem(numero, 0, celda)
            self.mapeo.setCellWidget(numero, 1, QComboBox())
        formulario = QFormLayout()
        formulario.addRow("Nombre del perfil:", self.nombre_perfil)
        formulario.addRow("Codificación:", self.codificacion)
        formulario.addRow("Separador:", self.separador)
        formulario.addRow("Formato de fecha:", self.formato_fecha)
        self.valores = QTableWidget(0, 3)
        self.valores.setHorizontalHeaderLabels(["Tipo", "Valor en el archivo", "Asociar a"])
        self.valores.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.valores.verticalHeader().setVisible(False)
        self.caja_valores = QGroupBox("Estados y prioridades del archivo que el perfil no conoce")
        QVBoxLayout(self.caja_valores).addWidget(self.valores)
        self.caja_valores.hide()
        caja_mapeo = QGroupBox("2. Formato y asociación de columnas (* obligatorio)")
        diseno_mapeo = QHBoxLayout(caja_mapeo)
        izquierda = QVBoxLayout()
        izquierda.addLayout(formulario)
        izquierda.addWidget(self.caja_valores)
        diseno_mapeo.addLayout(izquierda, 1)
        diseno_mapeo.addWidget(self.mapeo, 1)

        # 3. Vista previa
        self.boton_validar = QPushButton("Validar vista previa")
        self.boton_validar.clicked.connect(self.validar)
        self.boton_importar = QPushButton("Importar filas válidas")
        self.boton_importar.clicked.connect(self.importar)
        self.boton_errores = QPushButton("Exportar filas con error")
        self.boton_errores.setObjectName("secundario")
        self.boton_errores.clicked.connect(self.exportar_errores)
        self.progreso = QProgressBar()
        self.progreso.hide()
        self.resumen = QLabel()
        acciones = QHBoxLayout()
        for widget in (self.boton_validar, self.boton_importar, self.boton_errores):
            acciones.addWidget(widget)
        acciones.addWidget(self.progreso, 1)
        acciones.addWidget(self.resumen)
        self.vista_previa = TablaDatos(
            estado, "Vista previa de importación", columnas_personales=("Técnicos",),
            color_fila=lambda fila: COLOR_RESULTADO.get(fila.get("Resultado")),
        )
        caja_vista = QGroupBox("3. Vista previa: verde válida, amarillo con advertencia, rojo con error")
        diseno_vista = QVBoxLayout(caja_vista)
        diseno_vista.addLayout(acciones)
        diseno_vista.addWidget(self.vista_previa)

        # Historial
        self.historial = TablaDatos(estado, "Historial de importaciones", columnas_personales=("Usuario",))
        caja_historial = QGroupBox("Historial de importaciones")
        QVBoxLayout(caja_historial).addWidget(self.historial)

        divisor = QSplitter(Qt.Orientation.Vertical)
        superior = QWidget()
        diseno_superior = QVBoxLayout(superior)
        diseno_superior.setContentsMargins(0, 0, 0, 0)
        diseno_superior.addWidget(caja_archivo)
        diseno_superior.addWidget(caja_mapeo)
        divisor.addWidget(superior)
        divisor.addWidget(caja_vista)
        divisor.addWidget(caja_historial)
        divisor.setSizes([330, 380, 180])
        QVBoxLayout(self).addWidget(divisor)
        self._habilitar()

    # --- Ciclo de la pantalla ---

    def actualizar(self) -> None:
        self.historial.fijar_datos(carga.historial_importaciones(self.estado.conexion))

    def _habilitar(self) -> None:
        hay_archivo = self.fuente is not None
        self.boton_validar.setEnabled(hay_archivo)
        cargables = len(self.resultado.cargables) if self.resultado is not None else 0
        repetido = hay_archivo and carga.importacion_previa(self.estado.conexion, self.fuente.hash) is not None
        self.boton_importar.setEnabled(cargables > 0 and not repetido)
        self.boton_importar.setText(f"Importar filas válidas ({cargables})" if cargables else "Importar filas válidas")
        self.boton_errores.setEnabled(self.resultado is not None and self.resultado.conteo(ERROR) > 0)

    # --- 1. Archivo ---

    def elegir_archivo(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir exportación de GLPI", "", "CSV (*.csv);;Todos (*.*)")
        if ruta:
            self.cargar_archivo(Path(ruta))

    def cargar_archivo(self, ruta: Path) -> None:
        try:
            fuente = FuenteCSV(ruta, tamano_bloque=self.estado.config.importacion.tamano_bloque)
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self.fuente = fuente
        self.resultado = None
        self.vista_previa.fijar_datos(pd.DataFrame())
        self.resumen.clear()
        self.ruta.setText(str(ruta))
        compatible = mapeo.buscar_perfil_compatible(self.estado.conexion, fuente.formato.encabezados)
        self.perfil_base = compatible or mapeo.proponer_perfil(fuente.formato)
        avisos = []
        previa = carga.importacion_previa(self.estado.conexion, fuente.hash)
        if previa is not None:
            avisos.append(f"Este archivo ya se importó el {previa['fecha'][:16]} («{previa['archivo']}»). No se puede volver a cargar.")
        if compatible is None:
            avisos.append("No hay un perfil guardado para estas columnas: revise la asociación propuesta.")
        else:
            avisos.append(f"Se usa el perfil guardado «{compatible.nombre}».")
        if fuente.formato.fecha_ambigua:
            avisos.append("Las fechas del archivo admiten día/mes y mes/día: confirme el formato de fecha.")
        self.aviso.setText("\n".join(avisos))
        self.aviso.setVisible(bool(avisos))
        self._mostrar_perfil(self.perfil_base)
        self._habilitar()

    def _mostrar_perfil(self, perfil: mapeo.PerfilImportacion) -> None:
        self.nombre_perfil.setText(perfil.nombre)
        self.codificacion.setCurrentText(self.fuente.formato.codificacion)
        self.separador.setCurrentIndex(self.separador.findData(self.fuente.formato.separador))
        formato = perfil.formato_fecha or self.fuente.formato.formato_fecha
        if formato:
            self.formato_fecha.setCurrentIndex(self.formato_fecha.findData(formato))
        self._llenar_columnas(perfil.mapeo.columnas)
        self.valores.setRowCount(0)
        self.caja_valores.hide()

    def _llenar_columnas(self, columnas: dict[str, str]) -> None:
        for numero, campo in enumerate(mapeo.CAMPOS_TICKET):
            combo: QComboBox = self.mapeo.cellWidget(numero, 1)
            combo.clear()
            combo.addItems([SIN_ASIGNAR, *self.fuente.formato.encabezados])
            actual = columnas.get(campo.nombre)
            combo.setCurrentText(actual if actual in self.fuente.formato.encabezados else SIN_ASIGNAR)

    def _reformatear(self) -> None:
        if self.fuente is None:
            return
        columnas = self._columnas()
        try:
            self.fuente = self.fuente.con_ajustes(
                self.codificacion.currentText(), self.separador.currentData(), self.formato_fecha.currentData()
            )
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        self._llenar_columnas(columnas or mapeo.proponer_columnas(self.fuente.formato.encabezados))
        self.resultado = None
        self._habilitar()

    # --- 2. Perfil ---

    def _columnas(self) -> dict[str, str]:
        columnas = {}
        for numero, campo in enumerate(mapeo.CAMPOS_TICKET):
            texto = self.mapeo.cellWidget(numero, 1).currentText()
            if texto and texto != SIN_ASIGNAR:
                columnas[campo.nombre] = texto
        return columnas

    def perfil_actual(self) -> mapeo.PerfilImportacion:
        estados = dict(self.perfil_base.mapeo.estados)
        prioridades = dict(self.perfil_base.mapeo.prioridades)
        for fila in range(self.valores.rowCount()):
            tipo = self.valores.item(fila, 0).text()
            valor = self.valores.item(fila, 1).text()
            destino = self.valores.cellWidget(fila, 2).currentData()
            if destino is None:
                continue
            (estados if tipo == "Estado" else prioridades)[valor] = destino
        return mapeo.PerfilImportacion(
            nombre=self.nombre_perfil.text().strip(),
            separador=self.separador.currentData(),
            codificacion=self.codificacion.currentText(),
            formato_fecha=self.formato_fecha.currentData(),
            separador_multivalor=self.perfil_base.separador_multivalor,
            mapeo=mapeo.Mapeo(self._columnas(), estados, prioridades),
            id=self.perfil_base.id,
        )

    def _mostrar_valores_desconocidos(self, estados: set[str], prioridades: set[str]) -> None:
        anteriores = {
            (self.valores.item(f, 0).text(), self.valores.item(f, 1).text()): self.valores.cellWidget(f, 2).currentData()
            for f in range(self.valores.rowCount())
        }
        self.valores.setRowCount(0)
        for tipo, valores, opciones in (
            ("Estado", sorted(estados), NOMBRE_ESTADO.items()),
            ("Prioridad", sorted(prioridades), ((n, f"{NOMBRE_PRIORIDAD[n]} ({n})") for n in sorted(NOMBRE_PRIORIDAD, reverse=True))),
        ):
            opciones = list(opciones)
            for valor in valores:
                fila = self.valores.rowCount()
                self.valores.insertRow(fila)
                self.valores.setItem(fila, 0, QTableWidgetItem(tipo))
                self.valores.setItem(fila, 1, QTableWidgetItem(valor))
                combo = QComboBox()
                combo.addItem("(elegir)", None)
                for codigo, nombre in opciones:
                    combo.addItem(nombre, codigo)
                previo = anteriores.get((tipo, valor))
                if previo is not None:
                    combo.setCurrentIndex(combo.findData(previo))
                self.valores.setCellWidget(fila, 2, combo)
        self.caja_valores.setVisible(self.valores.rowCount() > 0)

    # --- 3. Validar e importar ---

    def validar(self) -> None:
        if self.fuente is None:
            return
        try:
            self.fuente = self.fuente.con_ajustes(
                self.codificacion.currentText(), self.separador.currentData(), self.formato_fecha.currentData()
            )
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        perfil = self.perfil_actual()
        errores = mapeo.errores_del_perfil(perfil, self.fuente.formato.encabezados)
        if errores:
            mostrar_error("Revise la asociación de columnas:\n- " + "\n- ".join(errores), self)
            return
        fuente = self.fuente

        def trabajo(avance):
            resultado = validacion.validar(fuente.obtener_tickets(), perfil)
            desconocidos = mapeo.valores_no_mapeados(resultado.originales, perfil.mapeo)
            return resultado, desconocidos

        self._ocupado(True, "Validando…")
        ejecutar(self, trabajo, self._validado, self._fallo)

    def _validado(self, datos) -> None:
        self._ocupado(False)
        self.resultado, (estados, prioridades) = datos
        self._mostrar_valores_desconocidos(estados, prioridades)
        filas = self.resultado.filas
        vista = pd.DataFrame({
            "Fila": filas["_fila"],
            "Resultado": filas["resultado"].map(TEXTO_RESULTADO),
            "Motivos": filas["motivos"],
            "ID": filas["id_glpi"].astype(object),
            "Título": filas["titulo"],
            "Estado": filas["estado"],
            "Prioridad": filas["prioridad"],
            "Técnicos": filas["tecnicos"].map(lambda t: ", ".join(t or ())),
            "Apertura": filas["fecha_apertura"].map(lambda f: "" if pd.isna(f) else f"{f:%d/%m/%Y %H:%M}"),
            "Última actualización": filas["ultima_actualizacion"].map(lambda f: "" if pd.isna(f) else f"{f:%d/%m/%Y %H:%M}"),
        })
        self.vista_previa.fijar_datos(vista)
        r = self.resultado
        self.resumen.setText(
            f"{r.filas_leidas} filas: {r.conteo(VALIDA)} válidas, "
            f"{r.conteo(ADVERTENCIA)} con advertencia, {r.conteo(ERROR)} con error"
        )
        if estados or prioridades:
            self.caja_valores.setTitle(
                "Asocie estos valores y vuelva a validar: las filas que los usan quedaron con error"
            )
        self._habilitar()

    def importar(self) -> None:
        if self.resultado is None or self.fuente is None:
            return
        perfil = self.perfil_actual()
        fuente, resultado, estado = self.fuente, self.resultado, self.estado
        sesion, config = estado.sesion, estado.config

        def trabajo(conexion, avance):
            guardado = mapeo.guardar_perfil(conexion, sesion, perfil, fuente.formato.encabezados)
            resumen = carga.importar(
                conexion, sesion, archivo=fuente.ruta.name, hash_archivo=fuente.hash, perfil=guardado,
                validacion=resultado, franjas=config.turnos, carpeta_respaldos=config.rutas.respaldos,
                retencion_respaldos=config.general.retencion_respaldos, progreso=avance,
            )
            # Después de cada importación se ejecutan los hallazgos (spec 08)
            resumen.hallazgos = hallazgos.detectar(conexion)
            return resumen

        self._ocupado(True, "Importando…")
        ejecutar(self, con_conexion(estado, trabajo), self._importado, self._fallo, self._avance)

    def _importado(self, resumen: carga.ResumenImportacion) -> None:
        self._ocupado(False)
        self.perfil_base = mapeo.buscar_perfil_compatible(self.estado.conexion, self.fuente.formato.encabezados) or self.perfil_base
        self.actualizar()
        self._habilitar()
        self.estado.datos_cambiados.emit()
        eventos = ", ".join(f"{k.lower()}: {v}" for k, v in sorted(resumen.eventos.items())) or "ninguno"
        mostrar_info(
            f"Importación terminada ({resumen.archivo}).\n\n"
            f"Tickets nuevos: {resumen.nuevos}\nActualizados: {resumen.actualizados}\n"
            f"Sin cambios: {resumen.sin_cambios}\nIgnorados por ser más antiguos: {resumen.omitidos_por_antiguos}\n"
            f"Filas con error (no cargadas): {resumen.filas_error}\n"
            f"Cambios registrados: {resumen.cambios}\nEventos detectados: {eventos}\n\n"
            f"Respaldo previo: {resumen.respaldo.name if resumen.respaldo else '—'}\n\n"
            f"Hallazgos: {resumen.hallazgos.nuevos} nuevos ({resumen.hallazgos.altas_nuevas} de severidad ALTA), "
            f"{resumen.hallazgos.cerrados} cerrados.",
            self,
        )

    def exportar_errores(self) -> None:
        if self.resultado is None:
            return
        sugerido = self.estado.config.rutas.exportaciones / f"filas_con_error_{self.fuente.ruta.stem}.csv"
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar filas con error", str(sugerido), "CSV (*.csv)")
        if not ruta:
            return
        try:
            validacion.exportar_errores(self.resultado, Path(ruta))
        except ErrorAplicacion as error:
            mostrar_error(error.mensaje, self)
            return
        mostrar_info(f"Filas con error guardadas en:\n{ruta}", self)

    # --- Apoyo ---

    def _ocupado(self, ocupado: bool, texto: str = "") -> None:
        for boton in (self.boton_validar, self.boton_importar, self.boton_errores):
            boton.setEnabled(not ocupado)
        self.progreso.setVisible(ocupado)
        self.progreso.setRange(0, 0)
        self.progreso.setFormat(texto)
        if not ocupado:
            self._habilitar()

    def _avance(self, hechas: int, total: int) -> None:
        self.progreso.setRange(0, total)
        self.progreso.setValue(hechas)
        self.progreso.setFormat(f"Importando… %v de %m")

    def _fallo(self, mensaje: str) -> None:
        self._ocupado(False)
        mostrar_error(mensaje, self)
