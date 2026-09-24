import os

import pytest

# Las pruebas de interfaz corren sin pantalla
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import seguridad  # noqa: E402
from core.db import base_datos  # noqa: E402


@pytest.fixture(autouse=True)
def bcrypt_rapido(monkeypatch):
    """bcrypt con el mínimo de rondas para que las pruebas sean rápidas."""
    monkeypatch.setattr(seguridad, "RONDAS_BCRYPT", 4)


@pytest.fixture
def bd(tmp_path):
    """BD nueva, migrada y con semillas."""
    conexion = base_datos.abrir(tmp_path / "analizador.db", tmp_path / "respaldos")
    yield conexion
    conexion.close()


@pytest.fixture
def coordinador(bd):
    """Sesión del primer coordinador (PIN 1234)."""
    usuario_id = seguridad.crear_usuario(
        bd, None, nombre="Coordinador", perfil=seguridad.COORDINADOR, pin="1234"
    )
    return seguridad.iniciar_sesion(bd, usuario_id, "1234")


@pytest.fixture
def consulta(bd, coordinador):
    """Sesión de un usuario de consulta sin técnico asociado (PIN 1111)."""
    usuario_id = seguridad.crear_usuario(
        bd, coordinador, nombre="Consulta", perfil=seguridad.CONSULTA, pin="1111"
    )
    return seguridad.iniciar_sesion(bd, usuario_id, "1111")
