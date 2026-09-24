import pytest

from core import seguridad
from core.db import base_datos


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
