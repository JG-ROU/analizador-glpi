"""Cambios de configuración con historial (PAN-13, RNF-09)."""

from datetime import date, datetime

import pytest

from ayudas import importar_diario, ticket
import generador_glpi as gen
from core import configuracion as cfg
from core import config, historial, rutas
from core.errores import ErrorPermiso, ErrorValidacion
from core.turnos import turno_para

RAIZ_PLANTILLA = config.NOMBRE_PLANTILLA


def valor(bd, clave):
    return bd.execute("SELECT valor FROM parametro WHERE clave = ?", (clave,)).fetchone()[0]


# --- Parámetros ---

def test_actualizar_parametro_con_historial(bd, coordinador):
    cfg.actualizar_parametro(bd, coordinador, "muestra_minima", "15")
    assert valor(bd, "muestra_minima") == "15"
    registro = historial.consultar(bd, entidad="parametro")[0]
    assert (registro["entidad_id"], registro["valor_anterior"], registro["valor_nuevo"]) == (
        "muestra_minima", "10", "15",
    )


def test_mismo_valor_no_deja_historial(bd, coordinador):
    cfg.actualizar_parametro(bd, coordinador, "horas_sin_actualizar_mediana", "24,0")
    assert historial.consultar(bd, entidad="parametro") == []


@pytest.mark.parametrize(
    "clave, texto, mensaje",
    [
        ("muestra_minima", "diez", "número entero"),
        ("muestra_minima", "0", "mayor o igual a 1"),
        ("prioridad_p1", "7", "menor o igual a 6"),
        ("muestra_minima", "", "no puede quedar vacío"),
        ("no_existe", "1", "No existe"),
    ],
)
def test_parametro_invalido(bd, coordinador, clave, texto, mensaje):
    with pytest.raises(ErrorValidacion, match=mensaje):
        cfg.actualizar_parametro(bd, coordinador, clave, texto)


def test_objetivo_sla_puede_quedar_vacio(bd, coordinador):
    cfg.actualizar_parametro(bd, coordinador, "sla_horas_urgente", "72,5")
    assert valor(bd, "sla_horas_urgente") == "72.5"
    cfg.actualizar_parametro(bd, coordinador, "sla_horas_urgente", "")
    assert valor(bd, "sla_horas_urgente") is None


def test_consulta_no_modifica_parametros(bd, consulta):
    with pytest.raises(ErrorPermiso):
        cfg.actualizar_parametro(bd, consulta, "muestra_minima", "20")


def test_cambiar_prioridad_p1_recalcula_tickets(bd, coordinador, tmp_path):
    tickets = [
        ticket(1, datetime(2026, 9, 1, 10), "Tecnico 01", "Muy urgente"),
        ticket(2, datetime(2026, 9, 1, 11), "Tecnico 01", "Mayor"),
        ticket(3, datetime(2026, 9, 1, 12), "Tecnico 01", "Muy urgente", (datetime(2026, 9, 2, 10), gen.ESCALADO)),
    ]
    importar_diario(bd, coordinador, tickets, datetime(2026, 9, 1), datetime(2026, 9, 2, 23), tmp_path)
    cfg.actualizar_parametro(bd, coordinador, "prioridad_p1", "5")
    filas = {f["id_glpi"]: (f["es_p1"], f["tipo_caso"]) for f in bd.execute("SELECT * FROM ticket")}
    assert filas == {1: (1, "CRITICO_P1"), 2: (1, "CRITICO_P1"), 3: (1, "CRITICO_P1")}
    cfg.actualizar_parametro(bd, coordinador, "prioridad_p1", "6")
    filas = {f["id_glpi"]: (f["es_p1"], f["tipo_caso"]) for f in bd.execute("SELECT * FROM ticket")}
    assert filas == {1: (0, "GESTION"), 2: (1, "CRITICO_P1"), 3: (0, "ESCALAMIENTO")}


# --- KPIs ---

def test_actualizar_umbrales_de_kpi(bd, coordinador):
    cfg.actualizar_kpi(bd, coordinador, "KPI-05", {"umbral_verde": 15, "umbral_amarillo": 30, "visible_dashboard": False})
    fila = bd.execute("SELECT * FROM kpi_definicion WHERE codigo = 'KPI-05'").fetchone()
    assert (fila["umbral_verde"], fila["umbral_amarillo"], fila["visible_dashboard"]) == (15, 30, 0)
    campos = {r["campo"] for r in historial.consultar(bd, entidad="kpi_definicion")}
    assert campos == {"umbral_verde", "umbral_amarillo", "visible_dashboard"}


@pytest.mark.parametrize(
    "codigo, cambios, mensaje",
    [
        ("KPI-05", {"umbral_verde": 30, "umbral_amarillo": 20}, "menor es mejor"),
        ("KPI-07", {"umbral_verde": 80, "umbral_amarillo": 90}, "mayor es mejor"),
        ("KPI-16", {"umbral_amarillo": 10}, "umbral verde antes"),
        ("KPI-05", {"nombre": "Otro"}, "No se puede modificar"),
        ("KPI-99", {"meta": 1}, "No existe"),
    ],
)
def test_umbrales_incoherentes(bd, coordinador, codigo, cambios, mensaje):
    with pytest.raises(ErrorValidacion, match=mensaje):
        cfg.actualizar_kpi(bd, coordinador, codigo, cambios)


# --- Técnicos ---

def crear_tecnico(bd):
    with bd:
        return bd.execute(
            "INSERT INTO tecnico (nombre_glpi, nombre_mostrar, creado_en) VALUES ('tec1', 'tec1', '2026-09-24')"
        ).lastrowid


def test_actualizar_tecnico(bd, coordinador):
    tecnico = crear_tecnico(bd)
    cfg.actualizar_tecnico(bd, coordinador, tecnico, nombre_mostrar=" Técnico  Uno ", turno="Día Intermedio",
                           activo=True, incluir_en_ranking=False)
    fila = bd.execute("SELECT * FROM tecnico WHERE id = ?", (tecnico,)).fetchone()
    assert (fila["nombre_mostrar"], fila["turno"], fila["incluir_en_ranking"]) == ("Técnico Uno", "Día Intermedio", 0)
    assert len(historial.consultar(bd, entidad="tecnico")) == 3


def test_turno_de_tecnico_invalido(bd, coordinador):
    with pytest.raises(ErrorValidacion, match="turno"):
        cfg.actualizar_tecnico(bd, coordinador, crear_tecnico(bd), nombre_mostrar="X", turno="Madrugada",
                               activo=True, incluir_en_ranking=True)


# --- Festivos ---

def test_festivos_propuestos_confirmados_y_eliminados(bd, coordinador):
    propuesta = cfg.proponer_festivos(2026)
    assert cfg.agregar_festivos(bd, coordinador, propuesta) == 18
    assert cfg.agregar_festivos(bd, coordinador, propuesta[:2]) == 0
    cfg.eliminar_festivo(bd, coordinador, date(2026, 1, 1))
    assert len(cfg.listar_festivos(bd)) == 17
    acciones = [r["accion"] for r in historial.consultar(bd, entidad="festivo")]
    assert acciones.count("CREAR") == 18 and acciones[0] == "ELIMINAR"


# --- Franjas de turno ---

def test_guardar_franjas_reescribe_config_y_recalcula(bd, coordinador, tmp_path):
    archivo = tmp_path / "config.ini"
    plantilla = (rutas.directorio_recursos() / RAIZ_PLANTILLA).read_text(encoding="utf-8")
    archivo.write_text(plantilla, encoding="utf-8")
    importar_diario(bd, coordinador, [ticket(1, datetime(2026, 9, 1, 13, 30), "Tecnico 01", "Baja")],
                    datetime(2026, 9, 1), datetime(2026, 9, 1, 23), tmp_path)
    assert bd.execute("SELECT turno_apertura FROM ticket").fetchone()[0] == "Mañana"

    nuevas = cfg.guardar_franjas(bd, coordinador, archivo, {
        "Mañana": "06:00-13:00", "Tarde": "13:00-21:00", "Nocturno": "21:00-06:00",
    })
    assert turno_para(datetime(2026, 9, 1, 13, 30).time(), nuevas) == "Tarde"
    assert bd.execute("SELECT turno_apertura FROM ticket").fetchone()[0] == "Tarde"

    cargada = config.cargar(archivo, tmp_path)
    assert [(f.turno, f.inicio, f.fin) for f in cargada.turnos] == [
        ("Mañana", 360, 780), ("Tarde", 780, 1260), ("Nocturno", 1260, 360),
    ]
    texto = archivo.read_text(encoding="utf-8")
    assert "No pueden solaparse" in texto and "[general]" in texto and "nivel_log = INFO" in texto
    assert historial.consultar(bd, entidad="config.ini")[0]["valor_nuevo"].startswith("Mañana = 06:00-13:00")


def test_franjas_solapadas_no_se_guardan(bd, coordinador, tmp_path):
    archivo = tmp_path / "config.ini"
    archivo.write_text("[turnos]\nMañana = 06:00-14:00\n", encoding="utf-8")
    with pytest.raises(Exception, match="se solapan"):
        cfg.guardar_franjas(bd, coordinador, archivo, {"Mañana": "06:00-14:00", "Tarde": "13:00-06:00"})
    assert archivo.read_text(encoding="utf-8") == "[turnos]\nMañana = 06:00-14:00\n"
