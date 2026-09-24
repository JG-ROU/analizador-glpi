"""Novedades (PAN-04), detalle de ticket (PAN-05), intentos de PIN e importaciones."""

from datetime import datetime, timedelta

import pytest

from ayudas import importar_diario, ticket
import generador_glpi as gen
from core import seguridad
from core.analisis import novedades as nov
from core.analisis import periodos
from core.errores import ErrorPermiso, ErrorValidacion
from core.importacion import carga

AHORA = datetime(2026, 9, 20, 12, 0)
SEPTIEMBRE = periodos.mes(2026, 9)


def h(dia, hora=10):
    return datetime(2026, 9, dia, hora, 0)


@pytest.fixture
def datos(bd, coordinador, tmp_path):
    tickets = [
        ticket(1, h(1), "Tecnico 01", "Mayor"),  # P1 abierto, sin actualizar desde el 1
        ticket(2, h(2), "Tecnico 02", "Mediana", (h(3), gen.RESUELTO)),  # resuelto sin cerrar
        ticket(3, h(4), "Tecnico 02", "Urgente", (h(5), gen.ESCALADO)),  # escalado antiguo
        ticket(4, h(18), "Tecnico 03", "Baja", (h(19), gen.ESCALADO)),  # escalado reciente
        ticket(5, h(10), "Tecnico 03", "Baja", (h(11), gen.RESUELTO), (h(12), gen.CERRADO)),
    ]
    importar_diario(bd, coordinador, tickets, h(1), h(19, 23), tmp_path)
    return bd


def ids(tabla):
    return sorted(tabla["ID"])


@pytest.mark.parametrize(
    "acceso, esperados",
    [
        (nov.TODOS, [1, 2, 3, 4, 5]),
        (nov.P1_ABIERTOS, [1]),
        (nov.SIN_CERRAR, [2]),
        (nov.ESCALADOS_ANTIGUOS, [3]),
        (nov.SIN_ACTUALIZAR, [1, 3, 4]),
    ],
)
def test_accesos_rapidos(datos, coordinador, acceso, esperados):
    assert ids(nov.listar(datos, coordinador, SEPTIEMBRE, acceso, ahora=AHORA)) == esperados


def test_columnas_y_valores(datos, coordinador):
    tabla = nov.listar(datos, coordinador, SEPTIEMBRE, nov.P1_ABIERTOS, ahora=AHORA)
    fila = tabla.iloc[0]
    assert list(tabla.columns) == list(nov.COLUMNAS)
    assert (fila["Estado"], fila["Prioridad"], fila["Técnico"], fila["Tipo de caso"]) == (
        "En curso (asignado)", "Mayor", "Tecnico 01", "Crítico P1",
    )
    assert fila["Horas sin actualizar"] == 458.0


def test_consulta_solo_ve_sus_tickets(datos, coordinador):
    tecnico = datos.execute("SELECT id FROM tecnico WHERE nombre_glpi = 'Tecnico 02'").fetchone()[0]
    usuario = seguridad.crear_usuario(datos, coordinador, nombre="T2", perfil=seguridad.CONSULTA,
                                      pin="2222", tecnico_id=tecnico)
    sesion = seguridad.iniciar_sesion(datos, usuario, "2222")
    assert ids(nov.listar(datos, sesion, SEPTIEMBRE, ahora=AHORA)) == [2, 3]
    assert nov.detalle(datos, sesion, 2).ticket["id_glpi"] == 2
    with pytest.raises(ErrorValidacion, match="no tiene permiso"):
        nov.detalle(datos, sesion, 1)


def test_jefatura_no_ve_tickets(datos, consulta):
    with pytest.raises(ErrorPermiso):
        nov.listar(datos, consulta, SEPTIEMBRE, ahora=AHORA)


def test_detalle_con_cambios_y_eventos(datos, coordinador):
    detalle = nov.detalle(datos, coordinador, 5)
    assert detalle.tecnicos == ["Tecnico 03"]
    assert [e["tipo"] for e in detalle.eventos] == ["SOLUCION", "CIERRE"]
    assert [(c["campo"], c["valor_nuevo"]) for c in detalle.cambios] == [
        ("estado", "Resueltas"), ("estado", "Cerrado"),
    ]


def test_acceso_desconocido(datos, coordinador):
    with pytest.raises(ErrorValidacion):
        nov.listar(datos, coordinador, SEPTIEMBRE, "OTRO", ahora=AHORA)


# --- Importaciones ---

def test_ultima_importacion_e_historial(datos):
    assert carga.ultima_importacion(datos) is not None
    tabla = carga.historial_importaciones(datos)
    assert len(tabla) >= 5 and tabla.iloc[0]["Usuario"] == "Coordinador"


def test_sin_importaciones(bd):
    assert carga.ultima_importacion(bd) is None
    assert carga.historial_importaciones(bd).empty


# --- Intentos de PIN ---

def test_espera_creciente_tras_fallos():
    control = seguridad.ControlIntentos()
    inicio = datetime(2026, 9, 24, 10, 0)
    assert [control.registrar_fallo(inicio) for _ in range(4)] == [0, 0, 0, 0]
    assert control.registrar_fallo(inicio) == 30
    assert control.segundos_restantes(inicio + timedelta(seconds=10)) == 21
    assert control.segundos_restantes(inicio + timedelta(seconds=31)) == 0
    assert control.registrar_fallo(inicio) == 60
    for _ in range(6):
        espera = control.registrar_fallo(inicio)
    assert espera == seguridad.ESPERA_MAXIMA_SEGUNDOS
    control.registrar_acierto()
    assert control.segundos_restantes(inicio) == 0 and control.registrar_fallo(inicio) == 0
