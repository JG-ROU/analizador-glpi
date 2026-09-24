import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import arranque, registro, reloj, rutas
from core.errores import ErrorAplicacion, ErrorConfiguracion

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def exe_simulado(tmp_path, monkeypatch):
    """Simula el .exe de PyInstaller: base junto al .exe y recursos en _MEIPASS."""
    carpeta_exe = tmp_path / "AnalizadorGLPI"
    recursos = carpeta_exe / "_internal"
    recursos.mkdir(parents=True)
    (recursos / "config.ini.ejemplo").write_bytes((RAIZ / "config.ini.ejemplo").read_bytes())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(carpeta_exe / "AnalizadorGLPI.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(recursos), raising=False)
    yield carpeta_exe
    logging.shutdown()


def test_directorios_en_desarrollo():
    assert not rutas.empaquetado()
    assert rutas.directorio_base() == RAIZ
    assert rutas.directorio_recursos() == RAIZ


def test_directorios_con_ejecutable(exe_simulado):
    assert rutas.empaquetado()
    assert rutas.directorio_base() == exe_simulado.resolve()
    assert rutas.directorio_recursos() == exe_simulado / "_internal"


def test_primer_arranque_crea_config_carpetas_y_bd_junto_al_exe(exe_simulado):
    contexto = arranque.arrancar()
    try:
        base = exe_simulado.resolve()
        assert contexto.config.archivo == base / "config.ini"
        for carpeta in ("data", "data/respaldos", "exportaciones", "logs"):
            assert (base / carpeta).is_dir(), carpeta
        assert (base / "data" / "analizador.db").is_file()
        assert len(list((base / "data" / "respaldos").glob("analizador_diario_*.db"))) == 1
        assert contexto.conexion.execute("PRAGMA user_version").fetchone()[0] >= 1
        contenido = (base / "logs" / "app.log").read_text(encoding="utf-8")
        assert "Inicio de Analizador GLPI" in contenido
    finally:
        contexto.conexion.close()


def test_config_invalido_queda_en_el_log_provisional(exe_simulado):
    (exe_simulado / "config.ini").write_text("[rutas]\n", encoding="utf-8")
    with pytest.raises(ErrorConfiguracion):
        arranque.arrancar()
    assert (exe_simulado / "logs" / "app.log").exists()


def test_crear_carpetas_sin_permiso_da_mensaje_en_espanol(tmp_path):
    archivo = tmp_path / "ocupado"
    archivo.write_text("x", encoding="utf-8")
    with pytest.raises(ErrorAplicacion, match="No se pudo crear la carpeta"):
        rutas.crear_carpetas([archivo / "sub"])


def test_registro_rota_y_no_duplica_manejadores(tmp_path):
    ruta = registro.configurar(tmp_path, "DEBUG")
    registro.configurar(tmp_path, "INFO")
    propios = [
        m for m in logging.getLogger().handlers if isinstance(m, registro._ManejadorAnalizador)
    ]
    assert len(propios) == 1
    assert propios[0].maxBytes == registro.TAMANO_MAXIMO_BYTES
    assert propios[0].backupCount == registro.COPIAS_ROTACION
    logging.getLogger("prueba").info("Acción con tilde: importación")
    propios[0].flush()
    assert "importación" in ruta.read_text(encoding="utf-8")
    logging.getLogger().removeHandler(propios[0])
    propios[0].close()


def test_ahora_es_hora_de_bogota_sin_zona():
    valor = reloj.ahora()
    esperado = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=5)
    assert valor.tzinfo is None
    assert valor.microsecond == 0
    assert abs(valor - esperado) < timedelta(seconds=5)
