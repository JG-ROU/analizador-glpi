"""Pruebas de la interfaz (pytest-qt, sin pantalla): PAN-01 a PAN-05, 07, 13 y 14.

Los cuadros de mensaje modales se reemplazan para que las pruebas no se detengan.
"""

import time
from datetime import datetime

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
from ui.pantallas import configuracion as pantalla_configuracion
from ui.pantallas import dashboard, importar, inicio_sesion, novedades, responsables
from ui.pantallas.dashboard import PantallaDashboard
from ui.pantallas.inicio_sesion import AsistenteConfiguracion, DialogoInicioSesion
from ui.ventana_principal import VentanaPrincipal


@pytest.fixture(autouse=True)
def sin_mensajes_modales(monkeypatch):
    mensajes = []
    for modulo in (importar, dashboard, novedades, responsables, pantalla_configuracion, inicio_sesion):
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
    assert titulos == ["Dashboard", "Importar", "Novedades", "Responsables", "Configuración", "Historial"]
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
        "Dashboard", "Novedades", "Responsables",
    ]
    ventana.menu.setCurrentRow(2)
    tabla = ventana.pantallas[2].tabla
    assert tabla.modelo.rowCount() == 1 and tabla.modelo.fila(0)["Técnico"] == "Tecnico 02"
    ventana.menu.setCurrentRow(1)
    ids = set(ventana.pantallas[1].tabla.modelo.datos["ID"])
    assert ids and ids <= {11, 12}


def test_jefatura_solo_ve_el_dashboard(qtbot, con_datos, coordinador):
    sesion = sesion_consulta(con_datos.conexion, coordinador, None)
    ventana = VentanaPrincipal(EstadoApp(con_datos, sesion))
    qtbot.addWidget(ventana)
    assert ventana.menu.count() == 1


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
    assert pantalla.tarjetas.count() == 10


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
