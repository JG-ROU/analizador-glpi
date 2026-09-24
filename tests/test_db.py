import shutil
import sqlite3

import pytest

from core.db import conexion as conexion_db, migrador, semilla
from core.dominio import PRIORIDADES
from core.errores import ErrorAplicacion

TABLAS_FASE_1 = {
    "migracion", "tecnico", "usuario", "perfil_importacion", "importacion", "ticket",
    "ticket_tecnico", "ticket_cambio", "ticket_evento", "kpi_definicion", "festivo",
    "parametro", "historial",
}


@pytest.fixture
def carpeta_migraciones(tmp_path):
    """Copia de las migraciones reales para agregar migraciones de prueba."""
    carpeta = tmp_path / "migraciones"
    shutil.copytree(migrador.CARPETA_MIGRACIONES, carpeta)
    return carpeta


def tablas(conexion):
    filas = conexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {fila[0] for fila in filas}


def insertar_historial(conexion):
    with conexion:
        conexion.execute(
            "INSERT INTO historial (entidad, entidad_id, accion, fecha_hora) "
            "VALUES ('parametro', 'muestra_minima', 'MODIFICAR', '2026-09-24 10:00:00')"
        )


# --- Conexión y esquema ---

def test_bd_nueva_queda_en_la_ultima_version_con_las_tablas_de_fase_1(bd):
    ultima = migrador.descubrir()[-1].version
    assert migrador.version_actual(bd) == ultima
    assert TABLAS_FASE_1 <= tablas(bd)
    registro = bd.execute("SELECT version, nombre FROM migracion WHERE version = 1").fetchone()
    assert tuple(registro) == (1, "inicial")


def test_conexion_con_claves_foraneas_y_wal(bd):
    assert bd.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert bd.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_clave_foranea_invalida_se_rechaza(bd):
    with pytest.raises(sqlite3.IntegrityError):
        with bd:
            bd.execute(
                "INSERT INTO usuario (nombre, perfil, tecnico_id, pin_hash, creado_en) "
                "VALUES ('x', 'CONSULTA', 999, 'h', '2026-09-24 10:00:00')"
            )


def test_estado_fuera_del_catalogo_se_rechaza(bd):
    with bd:
        bd.execute(
            "INSERT INTO importacion (tipo, archivo, hash, fecha) "
            "VALUES ('TICKETS', 'a.csv', 'h1', '2026-09-24 10:00:00')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        with bd:
            bd.execute(
                "INSERT INTO ticket (id_glpi, titulo, estado, estado_codigo, prioridad, "
                "prioridad_nivel, fecha_apertura, ultima_actualizacion, tipo_caso, "
                "turno_apertura, hash_fila, primera_importacion_id, ultima_importacion_id) "
                "VALUES (1, 't', 'Raro', 'RARO', 'Mediana', 3, '2026-09-01 08:00:00', "
                "'2026-09-01 08:00:00', 'GESTION', 'Mañana', 'x', 1, 1)"
            )


def test_tablas_estrictas_rechazan_tipos_incorrectos(bd):
    with pytest.raises(sqlite3.IntegrityError):
        with bd:
            bd.execute(
                "INSERT INTO importacion (tipo, archivo, hash, fecha, filas_leidas) "
                "VALUES ('TICKETS', 'a.csv', 'h2', '2026-09-24 10:00:00', 'muchas')"
            )


def test_bd_ilegible_da_mensaje_en_espanol(tmp_path):
    ruta = tmp_path / "danada.db"
    ruta.write_bytes(b"esto no es una base de datos" * 100)
    with pytest.raises(ErrorAplicacion, match="No se pudo abrir la base de datos"):
        conexion_db.conectar(ruta)


# --- Historial de solo inserción (RNF-09) ---

def test_historial_no_permite_update(bd):
    insertar_historial(bd)
    with pytest.raises(sqlite3.IntegrityError, match="solo inserción"):
        with bd:
            bd.execute("UPDATE historial SET accion = 'OTRA'")


def test_historial_no_permite_delete(bd):
    insertar_historial(bd)
    with pytest.raises(sqlite3.IntegrityError, match="solo inserción"):
        with bd:
            bd.execute("DELETE FROM historial")
    assert bd.execute("SELECT COUNT(*) FROM historial").fetchone()[0] == 1


# --- Migraciones (RNF-13, RNF-15) ---

def test_migrar_dos_veces_no_hace_nada_ni_respalda(bd, tmp_path):
    version = migrador.version_actual(bd)
    assert migrador.migrar(bd, tmp_path / "respaldos") == version
    assert not (tmp_path / "respaldos").exists()


def test_migracion_nueva_conserva_datos_y_respalda_antes(tmp_path, carpeta_migraciones):
    ruta = tmp_path / "analizador.db"
    respaldos = tmp_path / "respaldos"
    conexion = conexion_db.conectar(ruta)
    migrador.migrar(conexion, respaldos, carpeta_migraciones)
    semilla.sembrar(conexion)
    insertar_historial(conexion)
    version_previa = migrador.version_actual(conexion)

    siguiente = version_previa + 1
    (carpeta_migraciones / f"{siguiente:03d}_prueba.sql").write_text(
        "CREATE TABLE prueba (id INTEGER PRIMARY KEY) STRICT;", encoding="utf-8"
    )
    assert migrador.migrar(conexion, respaldos, carpeta_migraciones) == siguiente
    assert "prueba" in tablas(conexion)
    assert conexion.execute("SELECT COUNT(*) FROM historial").fetchone()[0] == 1

    copias = list(respaldos.glob(f"analizador_antes_migracion_v{version_previa}_*.db"))
    assert len(copias) == 1
    copia = sqlite3.connect(copias[0])
    assert copia.execute("PRAGMA user_version").fetchone()[0] == version_previa
    assert copia.execute("SELECT COUNT(*) FROM historial").fetchone()[0] == 1
    copia.close()
    conexion.close()


def test_migracion_fallida_deja_la_bd_como_estaba(tmp_path, carpeta_migraciones):
    conexion = conexion_db.conectar(tmp_path / "analizador.db")
    migrador.migrar(conexion, tmp_path / "respaldos", carpeta_migraciones)
    version_previa = migrador.version_actual(conexion)
    (carpeta_migraciones / f"{version_previa + 1:03d}_rota.sql").write_text(
        "CREATE TABLE a_medias (id INTEGER);\nESTO NO ES SQL;", encoding="utf-8"
    )
    with pytest.raises(ErrorAplicacion, match="Los datos no se modificaron"):
        migrador.migrar(conexion, tmp_path / "respaldos", carpeta_migraciones)
    assert migrador.version_actual(conexion) == version_previa
    assert "a_medias" not in tablas(conexion)
    conexion.close()


def test_bd_de_una_version_mas_reciente_se_rechaza(bd, tmp_path):
    bd.execute("PRAGMA user_version = 99")
    with pytest.raises(ErrorAplicacion, match="versión más reciente"):
        migrador.migrar(bd, tmp_path / "respaldos")


def test_migraciones_con_hueco_se_rechazan(carpeta_migraciones):
    (carpeta_migraciones / "009_salto.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ErrorAplicacion, match="faltantes o repetidas"):
        migrador.descubrir(carpeta_migraciones)


def test_migracion_con_nombre_invalido_se_rechaza(carpeta_migraciones):
    (carpeta_migraciones / "dos.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(ErrorAplicacion, match="nombre inválido"):
        migrador.descubrir(carpeta_migraciones)


# --- Semillas ---

def valor_parametro(conexion, clave):
    return conexion.execute("SELECT valor FROM parametro WHERE clave = ?", (clave,)).fetchone()[0]


def test_semilla_de_parametros(bd):
    assert valor_parametro(bd, "muestra_minima") == "10"
    assert valor_parametro(bd, "prioridad_p1") == "6"
    assert valor_parametro(bd, "dias_resuelto_sin_cerrar") == "2"
    assert valor_parametro(bd, "dias_importacion_desactualizada") == "1"
    for prioridad in PRIORIDADES:
        # La especificación prohíbe suponer los objetivos de SLA
        assert valor_parametro(bd, f"sla_horas_{prioridad.clave}") is None
        assert valor_parametro(bd, f"kpi06_verde_horas_{prioridad.clave}") is None
    assert valor_parametro(bd, "horas_sin_actualizar_mayor") == "1"
    assert valor_parametro(bd, "horas_sin_actualizar_urgente") == "4"
    assert valor_parametro(bd, "horas_sin_actualizar_mediana") == "24"


def test_semilla_de_kpis_predefinidos(bd):
    filas = bd.execute(
        "SELECT codigo, direccion, umbral_verde, umbral_amarillo, meta, critico, "
        "predefinido, calculo_especial FROM kpi_definicion ORDER BY orden"
    ).fetchall()
    assert [f["codigo"] for f in filas] == [
        "KPI-01", "KPI-02", "KPI-03", "KPI-04", "KPI-05", "KPI-06", "KPI-07", "KPI-08",
        "KPI-09", "KPI-10", "KPI-11", "KPI-12", "KPI-13", "KPI-14", "KPI-15", "KPI-16", "KPI-17",
    ]
    por_codigo = {f["codigo"]: f for f in filas}
    assert all(f["predefinido"] == 1 and f["calculo_especial"] == f["codigo"] for f in filas)
    kpi05 = por_codigo["KPI-05"]
    assert (kpi05["direccion"], kpi05["umbral_verde"], kpi05["umbral_amarillo"]) == (
        "MENOR_MEJOR", 20, 35,
    )
    assert por_codigo["KPI-04"]["meta"] == 100
    criticos = {f["codigo"] for f in filas if f["critico"]}
    assert criticos == {"KPI-04", "KPI-05", "KPI-07", "KPI-08"}


def test_resembrar_no_sobrescribe_cambios_del_usuario(bd):
    with bd:
        bd.execute("UPDATE parametro SET valor = '15' WHERE clave = 'muestra_minima'")
        bd.execute("UPDATE kpi_definicion SET umbral_verde = 25 WHERE codigo = 'KPI-05'")
        bd.execute("DELETE FROM parametro WHERE clave = 'dias_escalado_alerta'")
    semilla.sembrar(bd)
    assert valor_parametro(bd, "muestra_minima") == "15"
    assert bd.execute(
        "SELECT umbral_verde FROM kpi_definicion WHERE codigo = 'KPI-05'"
    ).fetchone()[0] == 25
    assert valor_parametro(bd, "dias_escalado_alerta") == "5"
