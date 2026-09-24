import sqlite3
from datetime import datetime

import pytest

from core import historial, reloj, seguridad
from core.db import migrador, respaldo
from core.errores import ErrorPermiso, ErrorValidacion
from core.seguridad import CONSULTA

INICIO = datetime(2026, 9, 24, 10, 0, 0)


class RelojFijo:
    """Reloj controlable para las pruebas."""

    def __init__(self, momento):
        self.momento = momento

    def __call__(self):
        return self.momento


@pytest.fixture
def reloj_fijo(monkeypatch):
    fijo = RelojFijo(INICIO)
    monkeypatch.setattr(reloj, "ahora", fijo)
    return fijo


@pytest.fixture
def carpeta(tmp_path):
    return tmp_path / "respaldos"


def festivos(conexion):
    return [f[0] for f in conexion.execute("SELECT fecha FROM festivo ORDER BY fecha")]


def agregar_festivo(conexion, fecha):
    with conexion:
        conexion.execute(
            "INSERT INTO festivo (fecha, descripcion) VALUES (?, 'Festivo')", (fecha,)
        )


# --- Crear respaldos ---

def test_respaldo_es_una_copia_consistente(bd, carpeta, reloj_fijo):
    agregar_festivo(bd, "2026-12-25")
    ruta = respaldo.respaldar(bd, carpeta, "manual")
    assert ruta.name == "analizador_manual_20260924_100000.db"
    copia = sqlite3.connect(ruta)
    assert festivos(copia) == ["2026-12-25"]
    copia.close()


def test_dos_respaldos_en_el_mismo_segundo_no_se_pisan(bd, carpeta, reloj_fijo):
    primero = respaldo.respaldar(bd, carpeta, "manual")
    segundo = respaldo.respaldar(bd, carpeta, "manual")
    assert primero != segundo
    assert segundo.name == "analizador_manual_20260924_100000_2.db"
    assert len(respaldo.listar(carpeta)) == 2


def test_respaldo_antes_de_importar(bd, carpeta, reloj_fijo):
    ruta = respaldo.respaldar_antes_de_importar(bd, carpeta, retencion_dias=30)
    assert ruta.name.startswith("analizador_antes_importacion_")


def test_respaldo_diario_solo_una_vez_por_dia(bd, carpeta, reloj_fijo):
    assert respaldo.respaldo_diario(bd, carpeta, 30) is not None
    reloj_fijo.momento = datetime(2026, 9, 24, 18, 0, 0)
    assert respaldo.respaldo_diario(bd, carpeta, 30) is None
    reloj_fijo.momento = datetime(2026, 9, 25, 7, 0, 0)
    assert respaldo.respaldo_diario(bd, carpeta, 30) is not None
    diarios = [r for r in respaldo.listar(carpeta) if r.motivo == "diario"]
    assert len(diarios) == 2


def test_listar_ordena_del_mas_reciente_al_mas_antiguo(bd, carpeta, reloj_fijo):
    respaldo.respaldar(bd, carpeta, "antes_importacion")
    reloj_fijo.momento = datetime(2026, 9, 25, 7, 0, 0)
    respaldo.respaldar(bd, carpeta, "antes_migracion_v1")
    (carpeta / "otro_archivo.db").write_bytes(b"")
    listado = respaldo.listar(carpeta)
    assert [r.motivo for r in listado] == ["antes_migracion_v1", "antes_importacion"]
    assert listado[0].fecha == datetime(2026, 9, 25, 7, 0, 0)
    assert listado[0].tamano_bytes > 0


def test_listar_carpeta_inexistente(tmp_path):
    assert respaldo.listar(tmp_path / "no_existe") == []


# --- Retención ---

def test_retencion_borra_los_vencidos_y_conserva_el_resto(bd, carpeta, reloj_fijo):
    for dia in (1, 10, 20):
        reloj_fijo.momento = datetime(2026, 9, dia, 8, 0, 0)
        respaldo.respaldar(bd, carpeta, "diario")
    (carpeta / "notas.txt").write_text("no es respaldo", encoding="utf-8")
    reloj_fijo.momento = datetime(2026, 9, 25, 8, 0, 0)
    borrados = respaldo.aplicar_retencion(carpeta, dias=10)
    assert [b.name for b in borrados] == ["analizador_diario_20260910_080000.db",
                                          "analizador_diario_20260901_080000.db"]
    assert [r.fecha.day for r in respaldo.listar(carpeta)] == [20]
    assert (carpeta / "notas.txt").exists()


def test_retencion_nunca_borra_el_ultimo_respaldo(bd, carpeta, reloj_fijo):
    reloj_fijo.momento = datetime(2026, 1, 1, 8, 0, 0)
    respaldo.respaldar(bd, carpeta, "diario")
    reloj_fijo.momento = datetime(2026, 9, 25, 8, 0, 0)
    assert respaldo.aplicar_retencion(carpeta, dias=30) == []
    assert len(respaldo.listar(carpeta)) == 1


# --- Restauración ---

def test_restaurar_recupera_los_datos_y_respalda_antes(bd, carpeta, reloj_fijo, coordinador):
    agregar_festivo(bd, "2026-12-25")
    ruta = respaldo.respaldar(bd, carpeta, "manual")
    agregar_festivo(bd, "2026-12-08")
    reloj_fijo.momento = datetime(2026, 9, 24, 11, 0, 0)

    previo = respaldo.restaurar(bd, coordinador, ruta, carpeta)

    assert festivos(bd) == ["2026-12-25"]
    assert previo.name == "analizador_antes_restauracion_20260924_110000.db"
    copia = sqlite3.connect(previo)
    assert festivos(copia) == ["2026-12-08", "2026-12-25"]
    copia.close()
    registro = historial.consultar(bd, entidad="base_datos")[0]
    assert registro["accion"] == "RESTAURAR"
    assert registro["valor_nuevo"] == ruta.name
    assert previo.name in registro["nota"]
    assert bd.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_restaurar_exige_coordinador(bd, carpeta, reloj_fijo, coordinador):
    ruta = respaldo.respaldar(bd, carpeta, "manual")
    usuario = seguridad.crear_usuario(bd, coordinador, nombre="Consulta", perfil=CONSULTA, pin="1111")
    sesion = seguridad.iniciar_sesion(bd, usuario, "1111")
    with pytest.raises(ErrorPermiso):
        respaldo.restaurar(bd, sesion, ruta, carpeta)


def test_restaurar_archivo_que_no_es_respaldo(bd, carpeta, tmp_path, coordinador):
    falso = tmp_path / "falso.db"
    falso.write_bytes(b"texto cualquiera" * 200)
    with pytest.raises(ErrorValidacion, match="no es un respaldo válido"):
        respaldo.restaurar(bd, coordinador, falso, carpeta)
    ajena = tmp_path / "ajena.db"
    otra = sqlite3.connect(ajena)
    otra.execute("CREATE TABLE cosa (id INTEGER)")
    otra.close()
    with pytest.raises(ErrorValidacion, match="no es un respaldo válido"):
        respaldo.restaurar(bd, coordinador, ajena, carpeta)
    assert respaldo.listar(carpeta) == []


def test_restaurar_respaldo_de_version_mas_reciente(bd, carpeta, reloj_fijo, coordinador):
    ruta = respaldo.respaldar(bd, carpeta, "manual")
    futura = sqlite3.connect(ruta)
    futura.execute("PRAGMA user_version = 99")
    futura.close()
    with pytest.raises(ErrorValidacion, match="más reciente"):
        respaldo.restaurar(bd, coordinador, ruta, carpeta)


def test_restaurar_archivo_inexistente(bd, carpeta, tmp_path, coordinador):
    with pytest.raises(ErrorValidacion, match="No existe"):
        respaldo.restaurar(bd, coordinador, tmp_path / "nada.db", carpeta)


def test_restaurar_respaldo_anterior_lo_migra(bd, carpeta, reloj_fijo, coordinador):
    ruta = respaldo.respaldar(bd, carpeta, "manual")
    assert migrador.version_actual(bd) >= 1
    respaldo.restaurar(bd, coordinador, ruta, carpeta)
    assert migrador.version_actual(bd) == migrador.descubrir()[-1].version
