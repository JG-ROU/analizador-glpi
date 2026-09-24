"""Pruebas de la interfaz (pytest-qt, sin pantalla): PAN-01 a PAN-05, 07, 13 y 14.

Los cuadros de mensaje modales se reemplazan para que las pruebas no se detengan.
"""

import time
from datetime import datetime
from pathlib import Path

import pytest

import generador_glpi as gen
from ayudas import importar_archivo, importar_diario
from core import config as config_core
from core import rutas, seguridad
from core.arranque import Contexto
from core.importacion import carga
from test_kpis import escenario
from ui import estilos
from ui.estado import EstadoApp
from ui.pantallas import clasificacion as pantalla_clasificacion
from ui.pantallas import configuracion as pantalla_configuracion
from ui.pantallas import kpis as pantalla_kpis
from ui.pantallas import dashboard, importar, inicio_sesion, novedades, responsables
from ui.pantallas.dashboard import PantallaDashboard
from ui.pantallas.inicio_sesion import AsistenteConfiguracion, DialogoInicioSesion
from ui.ventana_principal import VentanaPrincipal


@pytest.fixture(autouse=True)
def sin_mensajes_modales(monkeypatch):
    mensajes = []
    for modulo in (importar, dashboard, novedades, responsables, pantalla_configuracion, inicio_sesion,
                   pantalla_clasificacion, pantalla_kpis):
        for nombre in ("mostrar_error", "mostrar_info"):
            if hasattr(modulo, nombre):
                monkeypatch.setattr(modulo, nombre, lambda texto, padre=None, n=nombre: mensajes.append((n, texto)))
        if hasattr(modulo, "confirmar"):
            monkeypatch.setattr(modulo, "confirmar", lambda texto, padre=None: True)
    return mensajes


@pytest.fixture
def contexto(bd, tmp_path):
    archivo = tmp_path / "config.ini"
    archivo.write_text((rutas.directorio_recursos() / "config.ini.ejemplo").read_text(encoding="utf-8"), encoding="utf-8")
    configuracion = config_core.cargar(archivo, tmp_path)
    configuracion.rutas.respaldos.mkdir(parents=True, exist_ok=True)
    # La conexión de la prueba y la de los hilos deben apuntar a la misma BD
    ruta_bd = bd.execute("PRAGMA database_list").fetchone()["file"]
    rutas_bd = config_core.ConfigRutas(
        base_datos=type(configuracion.rutas.base_datos)(ruta_bd), respaldos=configuracion.rutas.respaldos,
        exportaciones=configuracion.rutas.exportaciones, logs=configuracion.rutas.logs,
    )
    return Contexto(config=config_core.Config(
        archivo=archivo, rutas=rutas_bd, importacion=configuracion.importacion,
        turnos=configuracion.turnos, general=configuracion.general,
    ), conexion=bd)


@pytest.fixture
def con_datos(contexto, coordinador, tmp_path):
    importar_diario(contexto.conexion, coordinador, escenario(), datetime(2026, 8, 25, 10),
                    datetime(2026, 10, 3, 23), tmp_path)
    return contexto


def sesion_consulta(bd, coordinador, tecnico):
    tecnico_id = None
    if tecnico:
        tecnico_id = bd.execute("SELECT id FROM tecnico WHERE nombre_glpi = ?", (tecnico,)).fetchone()[0]
    usuario = seguridad.crear_usuario(bd, coordinador, nombre=f"Usuario {tecnico}", perfil=seguridad.CONSULTA,
                                      pin="7777", tecnico_id=tecnico_id)
    return seguridad.iniciar_sesion(bd, usuario, "7777")


# --- PAN-01 ---

def test_asistente_de_primera_ejecucion(qtbot, contexto):
    asistente = AsistenteConfiguracion(contexto)
    qtbot.addWidget(asistente)
    asistente.coordinador.nombre.setText("Coordinadora")
    asistente.coordinador.pin.setText("2468")
    asistente.coordinador.pin2.setText("2468")
    asistente.turnos.tabla.item(0, 1).setText("06:00-13:00")
    asistente.turnos.tabla.item(1, 1).setText("13:00-22:00")
    asistente.prioridades.sla["urgente"].setText("72")
    asistente.prioridades.p1.setCurrentIndex(asistente.prioridades.p1.findData(5))
    asistente.accept()
    assert asistente.sesion is not None and asistente.sesion.es_coordinador
    valor = lambda clave: contexto.conexion.execute(  # noqa: E731
        "SELECT valor FROM parametro WHERE clave = ?", (clave,)).fetchone()[0]
    assert (valor("sla_horas_urgente"), valor("prioridad_p1"), valor("sla_horas_mediana")) == ("72", "5", None)
    assert contexto.config.turnos[0].texto == "06:00-13:00"
    assert "Mañana = 06:00-13:00" in contexto.config.archivo.read_text(encoding="utf-8")


def test_inicio_de_sesion(qtbot, contexto, coordinador):
    dialogo = DialogoInicioSesion(contexto)
    qtbot.addWidget(dialogo)
    dialogo.pin.setText("0000")
    dialogo.entrar()
    assert dialogo.sesion is None and "PIN incorrecto" in dialogo.mensaje.text()
    dialogo.pin.setText("1234")
    dialogo.entrar()
    assert dialogo.sesion == coordinador


def test_espera_tras_cinco_pin_incorrectos(qtbot, contexto, coordinador):
    dialogo = DialogoInicioSesion(contexto)
    qtbot.addWidget(dialogo)
    for _ in range(5):
        dialogo.pin.setText("0000")
        dialogo.entrar()
    assert "Espere" in dialogo.mensaje.text() and not dialogo.boton.isEnabled()


# --- Ventana principal y permisos (CA-08) ---

def test_menu_del_coordinador_y_todas_las_pantallas(qtbot, con_datos, coordinador):
    estilos.aplicar(qtbot_app())
    ventana = VentanaPrincipal(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(ventana)
    titulos = [ventana.menu.item(i).text() for i in range(ventana.menu.count())]
    assert titulos == ["Dashboard", "Importar", "Clasificación", "Novedades", "Hallazgos", "Estaciones",
                       "Tipificaciones", "Responsables", "Calidad", "Reportes", "KPIs", "Configuración", "Historial"]
    for indice in range(ventana.menu.count()):
        ventana.menu.setCurrentRow(indice)
    ventana.menu.setCurrentRow(0)
    qtbot.waitUntil(lambda: "calculado en" in ventana.pantallas[0].tiempo.text(), timeout=15000)
    assert "Última importación" in ventana.importacion.text()


def qtbot_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()


def test_consulta_ve_solo_sus_pantallas_y_metricas(qtbot, con_datos, coordinador):
    sesion = sesion_consulta(con_datos.conexion, coordinador, "Tecnico 02")
    ventana = VentanaPrincipal(EstadoApp(con_datos, sesion))
    qtbot.addWidget(ventana)
    assert [ventana.menu.item(i).text() for i in range(ventana.menu.count())] == [
        "Dashboard", "Novedades", "Estaciones", "Tipificaciones", "Responsables", "Calidad", "Reportes",
    ]
    ventana.menu.setCurrentRow(4)
    tabla = ventana.pantallas[4].tabla
    assert tabla.modelo.rowCount() == 1 and tabla.modelo.fila(0)["Técnico"] == "Tecnico 02"
    ventana.menu.setCurrentRow(1)
    ids = set(ventana.pantallas[1].tabla.modelo.datos["ID"])
    assert ids and ids <= {11, 12}


def test_jefatura_solo_ve_indicadores_agregados(qtbot, con_datos, coordinador):
    sesion = sesion_consulta(con_datos.conexion, coordinador, None)
    ventana = VentanaPrincipal(EstadoApp(con_datos, sesion))
    qtbot.addWidget(ventana)
    assert [ventana.menu.item(i).text() for i in range(ventana.menu.count())] == [
        "Dashboard", "Estaciones", "Tipificaciones", "Reportes"]
    for indice in (1, 2):
        ventana.menu.setCurrentRow(indice)


# --- PAN-02 Importar (CA-02, CA-03) ---

def test_pantalla_importar_de_punta_a_punta(qtbot, contexto, coordinador, tmp_path, sin_mensajes_modales):
    tickets = gen.generar_tickets(120, datetime(2026, 8, 1), datetime(2026, 9, 20), semilla=4)
    ruta = gen.escribir_csv(gen.inyectar_errores(gen.filas_en(tickets, datetime(2026, 9, 21)), 6), tmp_path / "glpi.csv")
    pantalla = importar.PantallaImportar(EstadoApp(contexto, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.cargar_archivo(ruta)
    assert pantalla.perfil_actual().mapeo.columnas["tecnico"] == "Asignado a: - Técnico"
    assert "No hay un perfil guardado" in pantalla.aviso.text()

    pantalla.validar()
    qtbot.waitUntil(lambda: pantalla.resultado is not None, timeout=10000)
    assert pantalla.resultado.conteo("ERROR") == 6
    assert pantalla.caja_valores.isVisibleTo(pantalla)  # estado y prioridad desconocidos
    assert pantalla.boton_importar.isEnabled()

    pantalla.importar()
    qtbot.waitUntil(lambda: any(n == "mostrar_info" for n, _ in sin_mensajes_modales), timeout=15000)
    cargados = contexto.conexion.execute("SELECT COUNT(*) FROM ticket").fetchone()[0]
    assert cargados == len(pantalla.resultado.cargables)
    assert pantalla.historial.modelo.rowCount() == 1
    assert not pantalla.boton_importar.isEnabled()  # el mismo archivo no se vuelve a importar

    pantalla.cargar_archivo(ruta)
    assert "ya se importó" in pantalla.aviso.text() and "perfil guardado «Exportación GLPI»" in pantalla.aviso.text()


def test_asociar_un_estado_desconocido(qtbot, contexto, coordinador, tmp_path):
    tickets = gen.generar_tickets(20, datetime(2026, 9, 1), datetime(2026, 9, 20), semilla=5)
    filas = gen.filas_en(tickets, datetime(2026, 9, 21))
    filas[0] = {**filas[0], "estado": "Pendiente de revisión"}
    ruta = gen.escribir_csv(filas, tmp_path / "glpi.csv")
    pantalla = importar.PantallaImportar(EstadoApp(contexto, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.cargar_archivo(ruta)
    pantalla.validar()
    qtbot.waitUntil(lambda: pantalla.resultado is not None, timeout=10000)
    assert pantalla.resultado.conteo("ERROR") == 1
    combo = pantalla.valores.cellWidget(0, 2)
    combo.setCurrentIndex(combo.findData("EN_ESPERA"))
    pantalla.resultado = None
    pantalla.validar()
    qtbot.waitUntil(lambda: pantalla.resultado is not None, timeout=10000)
    assert pantalla.resultado.conteo("ERROR") == 0


# --- PAN-03 Dashboard (CA-07) ---

def test_ca07_dashboard_en_menos_de_2_segundos(qtbot, contexto, coordinador, tmp_path):
    tickets = gen.generar_tickets(20000, datetime(2021, 9, 1), datetime(2026, 9, 20), semilla=8)
    ruta = gen.escribir_csv(gen.filas_en(tickets, datetime(2026, 9, 21)), tmp_path / "volumen.csv")
    importar_archivo(contexto.conexion, coordinador, ruta, tmp_path)
    pantalla = PantallaDashboard(EstadoApp(contexto, coordinador))
    qtbot.addWidget(pantalla)
    inicio = time.perf_counter()
    pantalla.actualizar()
    qtbot.waitUntil(lambda: "calculado en" in pantalla.tiempo.text(), timeout=20000)
    duracion = time.perf_counter() - inicio
    assert duracion < 2.0, f"El dashboard tardó {duracion:.2f} s"
    assert pantalla.tarjetas.count() == 17


def test_ca15_importacion_grande_no_congela_la_interfaz(qtbot, contexto, coordinador, tmp_path, sin_mensajes_modales):
    from PySide6.QtCore import QTimer

    tickets = gen.generar_tickets(20000, datetime(2021, 9, 1), datetime(2026, 9, 20), semilla=12)
    ruta = gen.escribir_csv(gen.filas_en(tickets, datetime(2026, 9, 21)), tmp_path / "volumen.csv")
    pantalla = importar.PantallaImportar(EstadoApp(contexto, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.cargar_archivo(ruta)
    pantalla.validar()
    qtbot.waitUntil(lambda: pantalla.resultado is not None, timeout=60000)
    avances, latidos = [], []
    pantalla.progreso.valueChanged.connect(avances.append)
    reloj_ui = QTimer()
    reloj_ui.timeout.connect(lambda: latidos.append(1))
    reloj_ui.start(50)
    pantalla.importar()
    assert pantalla.progreso.isVisibleTo(pantalla)
    qtbot.waitUntil(lambda: any(n == "mostrar_info" for n, _ in sin_mensajes_modales), timeout=120000)
    reloj_ui.stop()
    assert len(avances) >= 10 and max(avances) == 20000  # la barra avanzó bloque a bloque
    assert len(latidos) >= 5  # el bucle de eventos siguió atendiendo mientras se importaba


# --- PAN-04 y PAN-05 ---

def test_novedades_y_detalle(qtbot, con_datos, coordinador, monkeypatch):
    estado = EstadoApp(con_datos, coordinador)
    pantalla = novedades.PantallaNovedades(estado)
    qtbot.addWidget(pantalla)
    pantalla.actualizar()
    assert pantalla.tabla.modelo.rowCount() > 0
    pantalla.acceso.setCurrentIndex(pantalla.acceso.findData("SIN_CERRAR"))
    pantalla.actualizar()
    abiertos = []
    monkeypatch.setattr(novedades.DialogoDetalleTicket, "exec", lambda self: abiertos.append(self) or 0)
    pantalla.abrir_detalle(14)
    assert abiertos and abiertos[0].windowTitle() == "Ticket 14"


# --- PAN-07, PAN-13 y PAN-14 ---

def test_responsables_para_el_coordinador(qtbot, con_datos, coordinador):
    pantalla = responsables.PantallaResponsables(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.actualizar()
    assert pantalla.tabla.modelo.rowCount() == 4
    assert "_id" not in pantalla.tabla.datos_visibles().columns


def test_configuracion_guarda_con_historial(qtbot, con_datos, coordinador, sin_mensajes_modales):
    estado = EstadoApp(con_datos, coordinador)
    pantalla = pantalla_configuracion.PantallaConfiguracion(estado)
    qtbot.addWidget(pantalla)
    pantalla.actualizar()
    for fila in range(pantalla.parametros.rowCount()):
        if pantalla.parametros.item(fila, 1).text() == "muestra_minima":
            pantalla.parametros.item(fila, 3).setText("12")
    pantalla._guardar_parametros()
    assert ("mostrar_info", "Cambios guardados. Quedaron registrados en el historial.") in sin_mensajes_modales
    assert con_datos.conexion.execute("SELECT valor FROM parametro WHERE clave = 'muestra_minima'").fetchone()[0] == "12"
    assert pantalla.tecnicos.rowCount() == 4 and pantalla.usuarios.rowCount() == 1
    pantalla._crear_respaldo()
    assert pantalla.respaldos.rowCount() == 1
    assert pantalla.respaldos.item(0, 1).text() == "manual"


def test_clasificacion_de_varios_tickets(qtbot, con_datos, coordinador, sin_mensajes_modales):
    from PySide6.QtCore import QItemSelectionModel
    from core import clasificacion as cl

    norte = cl.guardar_estacion(con_datos.conexion, coordinador, nombre="Norte")
    pantalla = pantalla_clasificacion.PantallaClasificacion(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.actualizar()
    total = pantalla.tabla.modelo.rowCount()
    assert total == 12  # todos pendientes
    seleccion = pantalla.tabla.vista.selectionModel()
    for fila in (0, 1):
        seleccion.select(pantalla.tabla.filtro.index(fila, 0),
                         QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    elegidos = [int(f["ID"]) for f in pantalla.tabla.filas_seleccionadas()]
    pantalla.combos[cl.ESTACION].setCurrentIndex(pantalla.combos[cl.ESTACION].findData(norte))
    pantalla.combos[cl.CATEGORIA].setCurrentIndex(pantalla.combos[cl.CATEGORIA].findData("DAT-01"))
    pantalla.aplicar()
    filas = con_datos.conexion.execute(
        "SELECT ticket_id, estacion_id, categoria_codigo FROM ticket_clasificacion ORDER BY ticket_id").fetchall()
    assert [tuple(f) for f in filas] == [(i, norte, "DAT-01") for i in sorted(elegidos)]
    assert pantalla.tabla.modelo.rowCount() == total  # siguen pendientes: faltan causa y tipo de solución


def test_editor_de_kpis_crea_uno_nuevo(qtbot, con_datos, coordinador, sin_mensajes_modales):
    pantalla = pantalla_kpis.PantallaKPIs(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.actualizar()
    pantalla.nuevo()
    pantalla.nombre.setText("P1 abiertos")
    pantalla.tipo.setCurrentIndex(pantalla.tipo.findData("CONTEO"))
    pantalla.numerador.fijar([{"campo": "es_p1", "valor": True}])
    pantalla.vista_previa()
    assert "tickets" in pantalla.previa.text()
    pantalla.guardar()
    assert pantalla.codigo == "KPI-U01"
    fila = con_datos.conexion.execute("SELECT * FROM kpi_definicion WHERE codigo = 'KPI-U01'").fetchone()
    assert fila["nombre"] == "P1 abiertos" and fila["predefinido"] == 0


def test_editor_de_kpis_predefinido_solo_umbrales(qtbot, con_datos, coordinador, sin_mensajes_modales):
    pantalla = pantalla_kpis.PantallaKPIs(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.actualizar()
    pantalla.tabla.selectRow(4)  # KPI-05
    assert pantalla.codigo == "KPI-05" and not pantalla.nombre.isEnabled()
    pantalla.verde.setText("25")
    pantalla.amarillo.setText("40")
    pantalla.guardar()
    fila = con_datos.conexion.execute("SELECT umbral_verde, umbral_amarillo FROM kpi_definicion WHERE codigo = 'KPI-05'").fetchone()
    assert tuple(fila) == (25, 40)


def test_pantalla_de_hallazgos(qtbot, con_datos, coordinador, sin_mensajes_modales, monkeypatch):
    from PySide6.QtCore import QItemSelectionModel
    from ui.pantallas import hallazgos as pantalla_hallazgos

    monkeypatch.setattr(pantalla_hallazgos, "mostrar_error", lambda t, p=None: sin_mensajes_modales.append(("e", t)))
    monkeypatch.setattr(pantalla_hallazgos.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Revisado con el equipo", True)))
    estado = EstadoApp(con_datos, coordinador)
    pantalla = pantalla_hallazgos.PantallaHallazgos(estado)
    qtbot.addWidget(pantalla)
    pantalla.detectar()
    qtbot.waitUntil(lambda: "nuevos" in pantalla.estado_deteccion.text(), timeout=15000)
    assert pantalla.tabla.modelo.rowCount() > 0
    pantalla.tabla.vista.selectionModel().select(
        pantalla.tabla.filtro.index(0, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    elegido = int(pantalla.tabla.filas_seleccionadas()[0]["ID"])
    pantalla.revisar("REVISADO")
    fila = con_datos.conexion.execute("SELECT estado, comentario FROM hallazgo WHERE id = ?", (elegido,)).fetchone()
    assert tuple(fila) == ("REVISADO", "Revisado con el equipo")
    ventana = VentanaPrincipal(estado)
    qtbot.addWidget(ventana)
    assert ventana.campana.text().startswith("🔔")


def test_pantalla_de_reportes_genera_pdf(qtbot, con_datos, coordinador):
    from ui.pantallas.reportes import PantallaReportes

    pantalla = PantallaReportes(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.actualizar()
    assert pantalla.lista.count() == 10
    pantalla.lista.setCurrentRow(0)
    pantalla.generar()
    qtbot.waitUntil(lambda: pantalla.ultimo is not None, timeout=20000)
    assert pantalla.ultimo.suffix == ".pdf" and pantalla.ultimo.exists()
    pantalla.lista.setCurrentRow(7)  # REP-08
    assert pantalla.formulario.isRowVisible(pantalla.horas)


def test_resumenes_semanales_desde_reportes(qtbot, con_datos, coordinador, monkeypatch):
    from core import reloj
    from ui.pantallas import reportes as pantalla_reportes

    abiertos = []
    monkeypatch.setattr(pantalla_reportes.QDesktopServices, "openUrl", staticmethod(lambda url: abiertos.append(url)))
    monkeypatch.setattr(reloj, "ahora", lambda: datetime(2026, 9, 9, 8))  # semana resumida: 31-ago a 6-sep
    pantalla = pantalla_reportes.PantallaReportes(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(pantalla)
    boton = next(b for b in pantalla.findChildren(pantalla_reportes.QPushButton)
                 if b.text() == "Resúmenes semanales por técnico")
    boton.click()
    qtbot.waitUntil(lambda: "borradores de resumen semanal" in pantalla.resultado.text(), timeout=30000)
    carpeta = Path(abiertos[0].toLocalFile())
    assert carpeta.name.startswith("resumenes_") and list(carpeta.glob("resumen_*.eml"))


def test_barra_de_avisos_al_iniciar(qtbot, con_datos, coordinador):
    ventana = VentanaPrincipal(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(ventana)
    ventana.show()
    assert ventana.avisos.isVisible()
    assert "NOT-03" in ventana.texto_avisos.text()  # agosto sin paquete mensual
    ventana.ir_a("Reportes")
    assert ventana.pantallas[ventana.pila.currentIndex()].titulo == "Reportes"


def test_paquete_mensual_desde_reportes(qtbot, con_datos, coordinador, monkeypatch):
    from ui.pantallas import reportes as pantalla_reportes

    abiertos = []
    monkeypatch.setattr(pantalla_reportes.QDesktopServices, "openUrl", staticmethod(lambda url: abiertos.append(url)))
    monkeypatch.setattr(pantalla_reportes.DialogoPaquete, "exec", lambda self: pantalla_reportes.QDialog.DialogCode.Accepted)
    estado = EstadoApp(con_datos, coordinador)
    pantalla = pantalla_reportes.PantallaReportes(estado)
    qtbot.addWidget(pantalla)
    pantalla.generar_paquete()
    qtbot.waitUntil(lambda: "Paquete generado" in pantalla.resultado.text(), timeout=30000)
    assert abiertos and abiertos[0].toLocalFile().endswith("_correo.eml")


def test_ca16_panel_de_evaluacion_escalamiento(qtbot, con_datos, coordinador, monkeypatch):
    from ui.pantallas import calidad as pantalla_calidad
    from core.analisis import calidad as cal

    mensajes = []
    monkeypatch.setattr(pantalla_calidad, "mostrar_info", lambda t, p=None: mensajes.append(t))
    monkeypatch.setattr(pantalla_calidad, "mostrar_error", lambda t, p=None: mensajes.append("ERROR " + t))
    panel = pantalla_calidad.PanelEvaluacion(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(panel)
    panel.cargar(2)  # ticket escalado dos veces
    panel.tipo.setCurrentIndex(panel.tipo.findData("ESCALAMIENTO"))
    panel._cargar_criterios()
    assert [f.criterio for f in panel.filas] == [f"G-{n:02d}" for n in range(1, 13)] + [f"E-0{n}" for n in range(1, 7)]
    criticos = [f.criterio for f in panel.filas if f.findChildren(pantalla_calidad.QLabel, None) and
                any(l.text() == "CRÍTICO" for l in f.findChildren(pantalla_calidad.QLabel))]
    assert "G-02" in criticos and "E-05" in criticos
    for fila in panel.filas:
        if fila.casilla.valor is None:
            fila.casilla.fijar(cal.CUMPLE)
    assert "%" in panel.puntaje.text()
    panel.guardar()
    assert mensajes and not mensajes[-1].startswith("ERROR"), mensajes
    assert con_datos.conexion.execute("SELECT COUNT(*) FROM evaluacion WHERE ticket_id = 2").fetchone()[0] == 1


def test_pantalla_calidad_por_perfil(qtbot, con_datos, coordinador):
    from ui.pantallas.calidad import PantallaCalidad

    pantalla = PantallaCalidad(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(pantalla)
    pestanas = [pantalla.pestanas.tabText(i) for i in range(pantalla.pestanas.count())]
    assert pestanas == ["Evaluar tickets", "Histórico por técnico", "Rendimiento", "Comparativo y ranking",
                        "Incumplimiento por criterio"]
    pantalla.actualizar()
    for indice in range(pantalla.pestanas.count()):
        pantalla.pestanas.setCurrentIndex(indice)
    assert pantalla.historico.modelo.rowCount() == 8
    tecnico = sesion_consulta(con_datos.conexion, coordinador, "Tecnico 02")
    propia = PantallaCalidad(EstadoApp(con_datos, tecnico))
    qtbot.addWidget(propia)
    assert [propia.pestanas.tabText(i) for i in range(propia.pestanas.count())] == [
        "Histórico por técnico", "Rendimiento", "Incumplimiento por criterio"]
    propia.actualizar()
    assert propia.tecnico.count() == 1 and propia.tecnico.currentText() == "Tecnico 02"


def test_importar_seguimientos_desde_la_pantalla(qtbot, con_datos, coordinador, tmp_path, monkeypatch):
    from ui.pantallas import importar_seguimientos as panel_seg

    mensajes = []
    monkeypatch.setattr(panel_seg, "mostrar_info", lambda t, p=None: mensajes.append(t))
    monkeypatch.setattr(panel_seg, "mostrar_error", lambda t, p=None: mensajes.append("ERROR " + t))
    ruta = gen.escribir_csv_seguimientos(gen.filas_seguimientos(escenario(), datetime(2026, 10, 3, 23)),
                                         tmp_path / "seguimientos.csv")
    panel = panel_seg.PanelSeguimientos(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(panel)
    panel.cargar_archivo(ruta)
    assert panel.perfil().columnas["contenido"] == "Contenido"
    panel.validar()
    qtbot.waitUntil(lambda: panel.resultado is not None, timeout=15000)
    panel.importar()
    qtbot.waitUntil(lambda: bool(mensajes), timeout=15000)
    assert mensajes[-1].startswith("Seguimientos importados")
    assert con_datos.conexion.execute("SELECT COUNT(*) FROM seguimiento").fetchone()[0] > 0


def test_detalle_con_boton_evaluar(qtbot, con_datos, coordinador, monkeypatch):
    from ui.pantallas import calidad as pantalla_calidad

    abiertos = []
    monkeypatch.setattr(pantalla_calidad.DialogoEvaluacion, "exec", lambda self: abiertos.append(self) or 0)
    estado = EstadoApp(con_datos, coordinador)
    detalle = novedades.novedades.detalle(con_datos.conexion, coordinador, 2)
    dialogo = novedades.DialogoDetalleTicket(detalle, None, estado)
    qtbot.addWidget(dialogo)
    boton = next(b for b in dialogo.findChildren(novedades.QPushButton) if b.text() == "Evaluar calidad")
    assert boton.isEnabled()
    boton.click()
    assert abiertos and abiertos[0].panel.ticket_id == 2


def test_historial_muestra_los_cambios(qtbot, con_datos, coordinador):
    from ui.pantallas.historial import PantallaHistorial
    pantalla = PantallaHistorial(EstadoApp(con_datos, coordinador))
    qtbot.addWidget(pantalla)
    pantalla.actualizar()
    assert "IMPORTAR" in set(pantalla.tabla.modelo.datos["Acción"])


def test_ultima_importacion_en_la_barra(qtbot, contexto, coordinador):
    ventana = VentanaPrincipal(EstadoApp(contexto, coordinador))
    qtbot.addWidget(ventana)
    assert ventana.importacion.text() == "Sin importaciones"
    assert carga.ultima_importacion(contexto.conexion) is None
