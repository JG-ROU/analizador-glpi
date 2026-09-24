import sqlite3

import pytest

from core import historial, seguridad
from core.errores import ErrorAutenticacion, ErrorPermiso, ErrorValidacion
from core.seguridad import CONSULTA, COORDINADOR, Sesion

PIN_COORD = "1234"


def crear_tecnico(bd, nombre):
    with bd:
        cursor = bd.execute(
            "INSERT INTO tecnico (nombre_glpi, nombre_mostrar, creado_en) "
            "VALUES (?, ?, '2026-09-24 10:00:00')",
            (nombre, nombre),
        )
    return cursor.lastrowid


@pytest.fixture
def equipo(bd, coordinador):
    """Dos técnicos con usuario de consulta y un usuario de jefatura sin técnico."""
    t1, t2 = crear_tecnico(bd, "Tecnico 1"), crear_tecnico(bd, "Tecnico 2")
    u1 = seguridad.crear_usuario(
        bd, coordinador, nombre="Tecnico 1", perfil=CONSULTA, pin="1111", tecnico_id=t1
    )
    u2 = seguridad.crear_usuario(
        bd, coordinador, nombre="Tecnico 2", perfil=CONSULTA, pin="2222", tecnico_id=t2
    )
    jefe = seguridad.crear_usuario(
        bd, coordinador, nombre="Jefatura", perfil=CONSULTA, pin="3333"
    )
    return {
        "t1": t1, "t2": t2,
        "s1": seguridad.iniciar_sesion(bd, u1, "1111"),
        "s2": seguridad.iniciar_sesion(bd, u2, "2222"),
        "jefe": seguridad.iniciar_sesion(bd, jefe, "3333"),
    }


# --- PIN ---

@pytest.mark.parametrize("pin", ["123", "abcd", "12 34", "1234567890123", ""])
def test_pin_invalido(pin):
    with pytest.raises(ErrorValidacion, match="dígitos"):
        seguridad.hash_pin(pin)


def test_pin_se_guarda_con_hash_bcrypt(bd, coordinador):
    pin_hash = bd.execute(
        "SELECT pin_hash FROM usuario WHERE id = ?", (coordinador.usuario_id,)
    ).fetchone()[0]
    assert pin_hash.startswith("$2b$")
    assert PIN_COORD not in pin_hash
    assert seguridad.pin_correcto(PIN_COORD, pin_hash)
    assert not seguridad.pin_correcto("9999", pin_hash)


# --- Primer usuario e inicio de sesión ---

def test_sin_usuarios_se_detecta_la_primera_ejecucion(bd):
    assert not seguridad.hay_usuarios(bd)


def test_primer_usuario_debe_ser_coordinador(bd):
    with pytest.raises(ErrorPermiso):
        seguridad.crear_usuario(bd, None, nombre="X", perfil=CONSULTA, pin="1111")


def test_sin_sesion_no_se_crea_un_segundo_usuario(bd, coordinador):
    with pytest.raises(ErrorPermiso):
        seguridad.crear_usuario(bd, None, nombre="Otro", perfil=COORDINADOR, pin="1111")


def test_iniciar_sesion(bd, coordinador):
    assert coordinador == Sesion(coordinador.usuario_id, "Coordinador", COORDINADOR, None)
    assert coordinador.es_coordinador


def test_pin_incorrecto(bd, coordinador):
    with pytest.raises(ErrorAutenticacion, match="PIN incorrecto"):
        seguridad.iniciar_sesion(bd, coordinador.usuario_id, "0000")


def test_usuario_inactivo_no_inicia_sesion(bd, coordinador, equipo):
    seguridad.cambiar_estado_usuario(bd, coordinador, equipo["s1"].usuario_id, False)
    with pytest.raises(ErrorAutenticacion, match="inactivo"):
        seguridad.iniciar_sesion(bd, equipo["s1"].usuario_id, "1111")
    nombres = [f["nombre"] for f in seguridad.listar_usuarios_activos(bd)]
    assert "Tecnico 1" not in nombres


def test_lista_de_inicio_de_sesion_no_expone_hashes(bd, coordinador):
    fila = seguridad.listar_usuarios_activos(bd)[0]
    assert "pin_hash" not in fila.keys()


# --- Gestión de usuarios ---

def test_consulta_no_puede_crear_usuarios(bd, equipo):
    with pytest.raises(ErrorPermiso, match="coordinador"):
        seguridad.crear_usuario(bd, equipo["s1"], nombre="Z", perfil=CONSULTA, pin="1111")


def test_nombre_repetido(bd, coordinador):
    with pytest.raises(ErrorValidacion, match="Ya existe"):
        seguridad.crear_usuario(
            bd, coordinador, nombre=" Coordinador ", perfil=CONSULTA, pin="1111"
        )


def test_tecnico_inexistente(bd, coordinador):
    with pytest.raises(ErrorValidacion, match="técnico"):
        seguridad.crear_usuario(
            bd, coordinador, nombre="Z", perfil=CONSULTA, pin="1111", tecnico_id=99
        )


def test_no_se_desactiva_el_unico_coordinador(bd, coordinador):
    with pytest.raises(ErrorValidacion, match="único coordinador"):
        seguridad.cambiar_estado_usuario(bd, coordinador, coordinador.usuario_id, False)


def test_coordinador_restablece_pin(bd, coordinador, equipo):
    seguridad.restablecer_pin(bd, coordinador, equipo["s1"].usuario_id, "5555")
    seguridad.iniciar_sesion(bd, equipo["s1"].usuario_id, "5555")
    with pytest.raises(ErrorAutenticacion):
        seguridad.iniciar_sesion(bd, equipo["s1"].usuario_id, "1111")


def test_consulta_no_restablece_pin_ajeno(bd, equipo):
    with pytest.raises(ErrorPermiso):
        seguridad.restablecer_pin(bd, equipo["s1"], equipo["s2"].usuario_id, "5555")


def test_cambiar_pin_propio_exige_el_actual(bd, equipo):
    with pytest.raises(ErrorAutenticacion):
        seguridad.cambiar_pin_propio(bd, equipo["s1"], "0000", "7777")
    seguridad.cambiar_pin_propio(bd, equipo["s1"], "1111", "7777")
    seguridad.iniciar_sesion(bd, equipo["s1"].usuario_id, "7777")


# --- Permisos por técnico (CA-08 en core) ---

def test_coordinador_ve_a_cualquier_tecnico_o_a_todos(equipo, coordinador):
    assert seguridad.tecnico_permitido(coordinador, equipo["t2"]) == equipo["t2"]
    assert seguridad.tecnico_permitido(coordinador, None) is None


def test_consulta_solo_ve_sus_metricas(equipo):
    s1 = equipo["s1"]
    assert seguridad.tecnico_permitido(s1, None) == equipo["t1"]
    assert seguridad.tecnico_permitido(s1, equipo["t1"]) == equipo["t1"]
    with pytest.raises(ErrorPermiso, match="propias"):
        seguridad.tecnico_permitido(s1, equipo["t2"])


def test_jefatura_sin_tecnico_no_ve_metricas_individuales(equipo):
    with pytest.raises(ErrorPermiso, match="equipo"):
        seguridad.tecnico_permitido(equipo["jefe"], None)


def test_consulta_no_lista_usuarios(bd, equipo):
    with pytest.raises(ErrorPermiso):
        seguridad.listar_usuarios(bd, equipo["s1"])


# --- Historial ---

def test_cambios_de_usuarios_quedan_en_historial_sin_pin(bd, coordinador, equipo):
    seguridad.restablecer_pin(bd, coordinador, equipo["s1"].usuario_id, "5555")
    seguridad.cambiar_estado_usuario(bd, coordinador, equipo["s2"].usuario_id, False)
    registros = historial.consultar(bd, entidad="usuario")
    acciones = [r["accion"] for r in registros]
    assert acciones[:2] == ["DESACTIVAR", "RESTABLECER_PIN"]
    assert acciones.count("CREAR") == 4
    assert registros[0]["usuario"] == "Coordinador"
    for registro in registros:
        for campo in ("valor_anterior", "valor_nuevo", "nota"):
            assert "5555" not in (registro[campo] or "")
            assert "$2b$" not in (registro[campo] or "")


def test_historial_filtra_por_entidad_id(bd, coordinador, equipo):
    registros = historial.consultar(bd, entidad="usuario", entidad_id=equipo["s1"].usuario_id)
    assert [r["accion"] for r in registros] == ["CREAR"]


def test_si_falla_el_historial_no_se_guarda_el_cambio(bd, coordinador, equipo, monkeypatch):
    def fallar(*args, **kwargs):
        raise sqlite3.OperationalError("disco lleno")

    monkeypatch.setattr(historial, "registrar", fallar)
    with pytest.raises(sqlite3.OperationalError):
        seguridad.cambiar_estado_usuario(bd, coordinador, equipo["s1"].usuario_id, False)
    activo = bd.execute(
        "SELECT activo FROM usuario WHERE id = ?", (equipo["s1"].usuario_id,)
    ).fetchone()[0]
    assert activo == 1
