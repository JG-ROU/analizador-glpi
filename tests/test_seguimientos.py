"""Importación del CSV de seguimientos y tareas (Fase 3) y KPI-13."""

from datetime import datetime

import pytest

import generador_glpi as gen
from ayudas import importar_diario, importar_seguimientos, ticket
from core.analisis import periodos
from core.analisis.kpis import CalculadoraKPI
from core.errores import ErrorPermiso, ErrorValidacion
from core.fuentes.fuente_csv import FuenteCSV
from core.importacion import seguimientos as seg


def d(dia, hora=10, minuto=0):
    return datetime(2026, 9, dia, hora, minuto)


@pytest.fixture
def tickets():
    return [
        ticket(1, d(1), "Tecnico 01", "Urgente", (d(2), gen.ESCALADO), (d(4), gen.ASIGNADO), (d(5), gen.RESUELTO)),
        ticket(2, d(2), "Tecnico 02", "Mayor", (d(2, 16), gen.RESUELTO)),
    ]


@pytest.fixture
def datos(bd, coordinador, tickets, tmp_path):
    importar_diario(bd, coordinador, tickets, d(1), d(5, 23), tmp_path)
    return bd


def test_etiquetas_y_duracion():
    assert seg.etiqueta_de("[DIAG] 10:30\nHice: …") == "DIAG"
    assert seg.etiqueta_de("  [RECORDATORIO n.º 1/2] 12/09 10:00") == "RECORDATORIO"
    assert seg.etiqueta_de("CAUSA: CAU-01 | x") is None
    assert [seg.leer_duracion(t) for t in ("90", "1:30", "1 hora 30 minutos", "45 min", "", "x")] == [
        90, 90, 90, 45, None, None]


def test_generador_de_seguimientos_coherente(tickets):
    notas = gen.seguimientos_de(tickets[0])
    etiquetas = [seg.etiqueta_de(n["contenido"]) for n in notas]
    assert etiquetas[0] == "APERTURA" and "ESC" in etiquetas and "RETORNO" in etiquetas
    assert "SEG-ESC" in etiquetas
    assert notas[-1]["tipo"] == "SOLUCION" and notas[-1]["fecha"] == d(5)
    p1 = [seg.etiqueta_de(n["contenido"]) for n in gen.seguimientos_de(tickets[1])]
    assert {"P1-INICIO", "P1-ACT", "P1-RESTABLECIDO"} <= set(p1)


def test_importar_seguimientos(datos, coordinador, tickets, tmp_path):
    resumen = importar_seguimientos(datos, coordinador, tickets, d(5, 23), tmp_path)
    total = len(gen.filas_seguimientos(tickets, d(5, 23)))
    assert (resumen.nuevos, resumen.repetidos, resumen.filas_error) == (total, 0, 0)
    fila = datos.execute("SELECT * FROM seguimiento WHERE ticket_id = 1 ORDER BY fecha LIMIT 1").fetchone()
    assert (fila["etiqueta"], fila["tipo"]) == ("APERTURA", "SEGUIMIENTO")
    tarea = datos.execute("SELECT * FROM seguimiento WHERE tipo = 'TAREA' LIMIT 1").fetchone()
    assert tarea["etiqueta"] == "DIAG"
    registro = datos.execute("SELECT tipo, filas_validas FROM importacion WHERE tipo = 'SEGUIMIENTOS'").fetchone()
    assert tuple(registro) == ("SEGUIMIENTOS", total)


def test_reimportar_no_duplica_notas(datos, coordinador, tickets, tmp_path):
    importar_seguimientos(datos, coordinador, tickets, d(3, 23), tmp_path)
    antes = datos.execute("SELECT COUNT(*) FROM seguimiento").fetchone()[0]
    resumen = importar_seguimientos(datos, coordinador, tickets, d(5, 23), tmp_path)
    despues = datos.execute("SELECT COUNT(*) FROM seguimiento").fetchone()[0]
    assert resumen.repetidos == antes and despues == antes + resumen.nuevos
    with pytest.raises(ErrorValidacion, match="ya se importó"):
        importar_seguimientos(datos, coordinador, tickets, d(5, 23), tmp_path)


def test_notas_de_tickets_no_importados_y_errores(datos, coordinador, tmp_path):
    filas = [
        {"id_glpi": 1, "fecha": d(1, 11), "autor": "Tecnico 01", "tipo": "SEGUIMIENTO", "contenido": "[DIAG] ok",
         "categoria": "", "duracion": "", "privado": False},
        {"id_glpi": 999, "fecha": d(1, 11), "autor": "X", "tipo": "SEGUIMIENTO", "contenido": "nota",
         "categoria": "", "duracion": "", "privado": False},
        {"id_glpi": 1, "fecha": d(1, 12), "autor": "X", "tipo": "SEGUIMIENTO", "contenido": "  ",
         "categoria": "", "duracion": "", "privado": False},
    ]
    resumen = importar_seguimientos(datos, coordinador, [], d(5), tmp_path, filas=filas)
    assert (resumen.nuevos, resumen.filas_error) == (1, 2)


def test_perfil_propuesto_y_reutilizado(datos, coordinador, tickets, tmp_path):
    importar_seguimientos(datos, coordinador, tickets, d(5, 23), tmp_path)
    ruta = gen.escribir_csv_seguimientos(gen.filas_seguimientos(tickets, d(4)), tmp_path / "otro.csv")
    formato = FuenteCSV(ruta).formato
    perfil = seg.perfil_guardado(datos, formato)
    assert perfil is not None and perfil.columnas["contenido"] == "Contenido"
    assert perfil.columnas["ticket_id"] == "ID del ticket"


def test_consulta_no_importa(datos, consulta, tickets, tmp_path):
    with pytest.raises(ErrorPermiso):
        importar_seguimientos(datos, consulta, tickets, d(5, 23), tmp_path)


def test_kpi13_primera_respuesta(datos, coordinador, tickets, tmp_path):
    calc = CalculadoraKPI(datos, coordinador, d(30))
    sin = calc.calcular("KPI-13", periodos.mes(2026, 9))
    assert sin.valor is None and "Importe el CSV de seguimientos" in sin.notas[0]
    importar_seguimientos(datos, coordinador, tickets, d(5, 23), tmp_path)
    kpi = CalculadoraKPI(datos, coordinador, d(30)).calcular("KPI-13", periodos.mes(2026, 9))
    primeras = [min(n["fecha"] for n in gen.seguimientos_de(t)) for t in tickets]
    esperadas = sorted((p - t.apertura).total_seconds() / 3600 for p, t in zip(primeras, tickets))
    assert kpi.valor == round(sum(esperadas) / 2, 2) and kpi.cantidad == 2
