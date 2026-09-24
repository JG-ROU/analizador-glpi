import csv
import io
import re
from datetime import datetime

import pytest

import generador_glpi as gen
from core.dominio import MAPEO_ESTADOS_GLPI, MAPEO_PRIORIDADES_GLPI

DESDE = datetime(2026, 7, 1)
HASTA = datetime(2026, 9, 23, 23, 59)
CORTE = datetime(2026, 9, 23, 7, 0)
LINEA_ENCABEZADOS = (
    '"ID";"Título";"Entidad";"Estado";"Autor - Autor";"Asignado a: - Técnico";'
    '"Fecha de Apertura";"Última actualización";"Prioridad";"Ubicación";'
)


@pytest.fixture(scope="module")
def tickets():
    return gen.generar_tickets(600, DESDE, HASTA, semilla=42)


def leer(texto):
    return list(csv.reader(io.StringIO(texto, newline=""), delimiter=";"))


# --- Formato IMP-00 ---

def test_encabezados_exactos_y_punto_y_coma_final(tickets):
    texto = gen.texto_csv(gen.filas_en(tickets, CORTE))
    assert texto.splitlines()[0] == LINEA_ENCABEZADOS
    filas = leer(texto)
    assert all(len(fila) == 11 and fila[-1] == "" for fila in filas)


def test_valores_con_el_formato_real(tickets):
    filas = leer(gen.texto_csv(gen.filas_en(tickets, CORTE)))[1:]
    assert filas
    for fila in filas:
        assert re.fullmatch(r"\d{1,3}( \d{3})*", fila[0])
        assert fila[3] in MAPEO_ESTADOS_GLPI
        assert fila[8] in MAPEO_PRIORIDADES_GLPI
        for fecha in (fila[6], fila[7]):
            assert re.fullmatch(r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}", fecha)
            datetime.strptime(fecha, gen.FORMATO_FECHA)
        assert " > " in fila[2] and " > " in fila[9]


def test_varios_tecnicos_en_una_celda_con_saltos_de_linea(tickets):
    filas = leer(gen.texto_csv(gen.filas_en(tickets, CORTE)))[1:]
    multiples = [f[5] for f in filas if "\n" in f[5]]
    assert multiples
    assert any("\n\n" in celda for celda in multiples)
    for celda in multiples:
        nombres = [n for n in celda.split("\n") if n]
        assert len(nombres) >= 2 and all(n in gen.TECNICOS for n in nombres)


def test_id_con_separador_configurable():
    assert gen.formatear_id(346649) == "346 649"
    assert gen.formatear_id(346649, " ") == "346 649"
    assert gen.formatear_id(1234567) == "1 234 567"
    assert gen.formatear_id(649) == "649"


def test_comillas_internas_se_duplican():
    assert gen._campo('Dice "hola"') == '"Dice ""hola"""'


# --- Simulación ---

def test_misma_semilla_mismo_archivo(tmp_path):
    a = gen.generar_exportaciones(tmp_path / "a", 200, DESDE, HASTA, cortes=2, errores=3)
    b = gen.generar_exportaciones(tmp_path / "b", 200, DESDE, HASTA, cortes=2, errores=3)
    assert [r.read_bytes() for r in a] == [r.read_bytes() for r in b]


def test_distinta_semilla_distinto_archivo():
    uno = gen.texto_csv(gen.filas_en(gen.generar_tickets(50, DESDE, HASTA, 1), CORTE))
    dos = gen.texto_csv(gen.filas_en(gen.generar_tickets(50, DESDE, HASTA, 2), CORTE))
    assert uno != dos


def test_hay_casos_para_probar_eventos(tickets):
    assert any(t.veces_en(gen.ESCALADO) >= 2 for t in tickets), "escalado dos veces"
    assert any(t.veces_en(gen.RESUELTO) >= 2 for t in tickets), "reapertura"
    assert any(t.veces_en(gen.CERRADO) == 1 for t in tickets), "cierre"
    assert any(t.veces_en(gen.RESUELTO) == 1 and t.veces_en(gen.CERRADO) == 0 for t in tickets)
    assert any(t.veces_en(gen.NUEVO) == 1 for t in tickets), "sin asignar al inicio"
    assert any(t.veces_en(gen.ESPERA) >= 1 for t in tickets)
    assert any(t.veces_en(gen.PLANIFICADO) >= 1 for t in tickets)
    reasignados = [t for t in tickets if sum(c.tecnicos is not None for c in t.cambios) >= 2]
    assert reasignados
    assert any(sum(c.prioridad is not None for c in t.cambios) >= 2 for t in tickets)


def test_prioridades_repartidas(tickets):
    prioridades = {t.cambios[0].prioridad for t in tickets}
    assert prioridades == set(MAPEO_PRIORIDADES_GLPI)


def test_foto_respeta_la_fecha_de_corte(tickets):
    for ticket in tickets:
        foto = ticket.foto(CORTE)
        if ticket.apertura > CORTE:
            assert foto is None
            continue
        assert ticket.apertura <= foto["ultima_actualizacion"] <= CORTE
        vigentes = [c for c in ticket.cambios if c.fecha <= CORTE and c.estado]
        assert foto["estado"] == vigentes[-1].estado


def test_foto_con_ticket_armado_a_mano():
    """Los escenarios de prueba de KPIs (T12) se arman así, con fechas exactas."""
    ticket = gen.TicketFicticio(
        1001, "Prueba", gen.ENTIDAD_BASE, "Autor 001", "Ubicación", datetime(2026, 9, 1, 8, 0),
        cambios=[
            gen.Cambio(datetime(2026, 9, 1, 8, 0), estado=gen.ASIGNADO,
                       tecnicos=("Tecnico 01",), prioridad="Urgente"),
            gen.Cambio(datetime(2026, 9, 2, 9, 0), estado=gen.ESCALADO),
            gen.Cambio(datetime(2026, 9, 3, 9, 0), tecnicos=("Tecnico 02",)),
            gen.Cambio(datetime(2026, 9, 4, 9, 0), estado=gen.RESUELTO),
        ],
        actualizaciones=[datetime(2026, 9, 2, 15, 30)],
    )
    antes = ticket.foto(datetime(2026, 9, 2, 12, 0))
    assert (antes["estado"], antes["tecnicos"]) == (gen.ESCALADO, ("Tecnico 01",))
    assert antes["ultima_actualizacion"] == datetime(2026, 9, 2, 9, 0)
    despues = ticket.foto(datetime(2026, 9, 3, 12, 0))
    assert (despues["estado"], despues["tecnicos"]) == (gen.ESCALADO, ("Tecnico 02",))
    assert despues["ultima_actualizacion"] == datetime(2026, 9, 3, 9, 0)
    assert ticket.foto(datetime(2026, 8, 31)) is None


# --- Cortes y errores ---

def test_cortes_diarios():
    assert gen.cortes_diarios(datetime(2026, 9, 23, 23, 59), 3) == [
        datetime(2026, 9, 21, 7, 0), datetime(2026, 9, 22, 7, 0), datetime(2026, 9, 23, 7, 0)
    ]
    assert gen.cortes_diarios(datetime(2026, 9, 23, 6, 0), 1) == [datetime(2026, 9, 22, 7, 0)]


def test_exportaciones_sucesivas_crecen_y_cambian(tmp_path):
    rutas = gen.generar_exportaciones(tmp_path, 300, DESDE, HASTA, cortes=3)
    assert [r.name for r in rutas] == [
        "glpi_tickets_20260921_0700.csv", "glpi_tickets_20260922_0700.csv",
        "glpi_tickets_20260923_0700.csv", "glpi_seguimientos_20260923_0700.csv",
    ]
    contenidos = [leer(r.read_text(encoding="utf-8"))[1:] for r in rutas[:3]]
    ids = [{f[0] for f in filas} for filas in contenidos]
    assert ids[0] <= ids[1] <= ids[2]
    estados_1 = {f[0]: f[3] for f in contenidos[1]}
    estados_2 = {f[0]: f[3] for f in contenidos[2]}
    assert any(estados_1[i] != estados_2[i] for i in estados_1)


def test_errores_de_validacion_inyectados(tickets):
    filas = gen.inyectar_errores(gen.filas_en(tickets, CORTE), 6)
    con_error = {f["error"]: f for f in filas if "error" in f}
    assert set(con_error) == {
        "fecha_invalida", "id_vacio", "id_no_numerico", "id_duplicado",
        "estado_sin_mapear", "prioridad_sin_mapear",
    }
    validos = {f["id_glpi"] for f in filas if "error" not in f}
    assert con_error["id_duplicado"]["id_glpi"] in validos
    texto = gen.texto_csv(filas)
    assert '"31-02-2026 10:00"' in texto and '"34A 123"' in texto
    assert '"Pendiente de revisión"' in texto and '"Crítica"' in texto


def test_codificacion_latin1(tmp_path):
    ruta = gen.generar_exportaciones(tmp_path, 20, DESDE, HASTA, codificacion="cp1252")[0]
    assert "Título".encode("latin-1") in ruta.read_bytes()


def test_linea_de_comandos(tmp_path, capsys):
    rutas = gen.main([
        "--tickets", "50", "--desde", "2026-08-01", "--hasta", "2026-09-23",
        "--cortes", "2", "--errores", "2", "--salida", str(tmp_path),
    ])
    assert len(rutas) == 3 and all(r.exists() for r in rutas)
    assert str(rutas[-1]) in capsys.readouterr().out
