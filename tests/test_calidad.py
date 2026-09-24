"""Evaluación de calidad: CAL-01, CAL-02, CAL-03 (CA-16, CA-17, CA-18)."""

from datetime import datetime

import pytest

import generador_glpi as gen
from ayudas import importar_diario, importar_seguimientos, ticket
from core import clasificacion as cl
from core import historial
from core.analisis import calidad as cal
from core.errores import ErrorPermiso, ErrorValidacion


def d(dia, hora=10, minuto=0):
    return datetime(2026, 9, dia, hora, minuto)


def nota(ticket_id, fecha, contenido, tipo="SEGUIMIENTO", categoria="", duracion=""):
    return {"id_glpi": ticket_id, "fecha": fecha, "autor": "Tecnico 01", "tipo": tipo, "contenido": contenido,
            "categoria": categoria, "duracion": duracion, "privado": False}


@pytest.fixture
def escalado(bd, coordinador, tmp_path):
    """Ticket Urgente escalado con seguimientos controlados."""
    t = ticket(1, d(1, 8), "Tecnico 01", "Urgente", (d(1, 12), gen.ESCALADO), (d(2, 9), gen.ASIGNADO),
               (d(2, 12), gen.RESUELTO))
    importar_diario(bd, coordinador, [t], d(1), d(2, 23), tmp_path)
    notas = [
        nota(1, d(1, 8, 10), "[APERTURA] 08:10\nEstación: Norte\nAplicación: Recaudo\nSíntoma: error\nImpacto: 1 carril"),
        nota(1, d(1, 9), "[DIAG] 09:00\nHice: reinicio\nEncontré: sigue\nEstado: hipótesis\nSigue: revisar – yo – antes de 11:00",
             "TAREA", "DIAG", "30"),
        nota(1, d(1, 12), "[ESC] 12:00\nEscalado a: Desarrollo | Ref.: #99\nMotivo: no resuelve\nPruebas: logs\nSe solicita: corrección"),
        nota(1, d(1, 15), "[SEG-ESC] 01/09 15:00\nConsulté a: Desarrollo\nSigue: nuevo seguimiento – yo – 01/09 18:00"),
        nota(1, d(1, 23), "[SEG-ESC] 01/09 23:00\nConsulté a: Desarrollo\nSigue: nuevo seguimiento – yo – 02/09 03:00"),
        nota(1, d(2, 9), "[RETORNO] 09:00\nEl área respondió\nVerificación: con el operador"),
        nota(1, d(2, 12), "CAUSA: CAU-03 | defecto\nSe actualizó la versión\nVerificación: con el operador a las 12:05", "SOLUCION"),
    ]
    importar_seguimientos(bd, coordinador, [], d(2, 23), tmp_path, filas=notas)
    return bd


# --- CA-16 ---

def test_ca16_escalamiento_muestra_12_generales_y_6_de_escalamiento(bd):
    criterios = cal.criterios_para(bd, "ESCALAMIENTO")
    ids = [c["id"] for c in criterios]
    assert ids[:12] == [f"G-{n:02d}" for n in range(1, 13)]
    assert ids[12:] == ["E-01", "E-02", "E-03", "E-04", "E-05", "E-06"]
    criticos = {c["id"] for c in criterios if c["critico"]}
    assert criticos == {"G-02", "G-05", "G-07", "G-10", "G-11", "E-01", "E-05"}


def test_criterios_por_tipo_de_caso(bd):
    assert len(cal.criterios_para(bd, "GESTION")) == 14
    assert len(cal.criterios_para(bd, "CRITICO_P1")) == 16
    with pytest.raises(ErrorValidacion):
        cal.criterios_para(bd, "OTRO")


# --- CA-17 ---

def test_ca17_puntaje_82_por_mejorar_y_no_conforme_con_critico():
    resultados = {f"X-{n}": cal.CUMPLE for n in range(14)} | {f"Y-{n}": cal.NO_CUMPLE for n in range(3)}
    puntaje = cal.calcular_puntaje(resultados, criticos=set(), umbral_conforme=90, umbral_por_mejorar=70)
    assert (puntaje.porcentaje, puntaje.resultado) == (82.35, cal.POR_MEJORAR)
    con_critico = cal.calcular_puntaje(resultados, criticos={"Y-0"}, umbral_conforme=90, umbral_por_mejorar=70)
    assert (con_critico.criticos_fallidos, con_critico.resultado) == (1, cal.NO_CONFORME)


def test_no_aplica_no_cuenta_y_limites():
    base = {"A": cal.CUMPLE, "B": cal.CUMPLE, "C": cal.NO_APLICA}
    assert cal.calcular_puntaje(base, set(), 90, 70).porcentaje == 100.0
    nueve = {f"A{n}": cal.CUMPLE for n in range(9)} | {"N": cal.NO_CUMPLE}
    assert cal.calcular_puntaje(nueve, set(), 90, 70).resultado == cal.CONFORME
    siete = {f"A{n}": cal.CUMPLE for n in range(7)} | {f"N{n}": cal.NO_CUMPLE for n in range(3)}
    assert cal.calcular_puntaje(siete, set(), 90, 70).resultado == cal.POR_MEJORAR


# --- CAL-02 y CA-18 ---

def test_ca18_precalifica_g07_y_e05(escalado):
    automaticos = cal.precalificar(escalado, 1, "ESCALAMIENTO", ahora=d(3))
    assert automaticos["G-07"].resultado == cal.CUMPLE  # nota de solución con CAUSA: CAU-03
    assert automaticos["E-05"].resultado == cal.NO_CUMPLE  # 8 h entre SEG-ESC y máximo 4 h (Urgente)
    assert automaticos["E-01"].resultado == cal.CUMPLE and automaticos["E-03"].resultado == cal.CUMPLE
    assert automaticos["G-01"].resultado == cal.CUMPLE and automaticos["G-06"].resultado == cal.CUMPLE
    assert automaticos["G-02"].resultado == cal.NO_CUMPLE  # sin clasificar
    assert "G-11" not in automaticos  # sin datos sensibles: queda manual
    assert "G-12" not in automaticos and "E-02" not in automaticos  # manuales


def test_g02_con_la_clasificacion(escalado, coordinador):
    norte = cl.guardar_estacion(escalado, coordinador, nombre="Norte")
    cl.clasificar(escalado, coordinador, [1], {cl.ESTACION: norte, cl.CATEGORIA: "APL-01"})
    assert cal.precalificar(escalado, 1, "ESCALAMIENTO", ahora=d(3))["G-02"].resultado == cal.CUMPLE


def completar(bd, tipo, automaticos, **cambios):
    resultados = {}
    for criterio in cal.criterios_para(bd, tipo):
        base = automaticos[criterio["id"]].resultado if criterio["id"] in automaticos else cal.CUMPLE
        resultados[criterio["id"]] = cambios.get(criterio["id"].replace("-", "_"), (base, None))
    return resultados


def test_ca18_corregir_un_automatico_exige_nota_y_queda_en_historial(escalado, coordinador):
    automaticos = cal.precalificar(escalado, 1, "ESCALAMIENTO", ahora=d(3))
    sin_nota = completar(escalado, "ESCALAMIENTO", automaticos, E_05=(cal.CUMPLE, ""))
    with pytest.raises(ErrorValidacion, match="Explique"):
        cal.guardar_evaluacion(escalado, coordinador, 1, "ESCALAMIENTO", sin_nota, ahora=d(3))
    con_nota = completar(escalado, "ESCALAMIENTO", automaticos, E_05=(cal.CUMPLE, "El área confirmó por teléfono"))
    cal.guardar_evaluacion(escalado, coordinador, 1, "ESCALAMIENTO", con_nota, "Buen escalamiento", ahora=d(3))
    evaluacion, detalle = cal.evaluacion_vigente(escalado, coordinador, 1)
    origenes = {f["criterio_id"]: f["origen"] for f in detalle}
    assert origenes["E-05"] == cal.AUTO_CORREGIDO and origenes["G-07"] == cal.AUTO and origenes["G-12"] == cal.MANUAL
    corregido = next(r for r in historial.consultar(escalado, entidad="evaluacion") if r["accion"] == "AUTO_CORREGIDO")
    assert (corregido["campo"], corregido["valor_anterior"], corregido["valor_nuevo"]) == ("E-05", "N", "C")
    assert corregido["nota"] == "El área confirmó por teléfono"


def test_versiones_y_tipo_de_caso_corregido(escalado, coordinador):
    automaticos = cal.precalificar(escalado, 1, "ESCALAMIENTO", ahora=d(3))
    cal.guardar_evaluacion(escalado, coordinador, 1, "ESCALAMIENTO", completar(escalado, "ESCALAMIENTO", automaticos), ahora=d(3))
    gestion = cal.precalificar(escalado, 1, "GESTION", ahora=d(4))
    cal.guardar_evaluacion(escalado, coordinador, 1, "GESTION", completar(escalado, "GESTION", gestion), ahora=d(4))
    filas = escalado.execute("SELECT version, vigente, tipo_caso FROM evaluacion WHERE ticket_id = 1 ORDER BY version").fetchall()
    assert [tuple(f) for f in filas] == [(1, 0, "ESCALAMIENTO"), (2, 1, "GESTION")]
    ticket_fila = escalado.execute("SELECT tipo_caso, tipo_caso_origen FROM ticket WHERE id_glpi = 1").fetchone()
    assert tuple(ticket_fila) == ("GESTION", "MANUAL")


def test_evaluacion_incompleta_o_sin_permiso(escalado, coordinador, consulta):
    with pytest.raises(ErrorValidacion, match="Falta calificar"):
        cal.guardar_evaluacion(escalado, coordinador, 1, "ESCALAMIENTO", {"G-01": (cal.CUMPLE, None)})
    with pytest.raises(ErrorPermiso):
        cal.guardar_evaluacion(escalado, consulta, 1, "ESCALAMIENTO", {})
    with pytest.raises(ErrorPermiso):
        cal.evaluacion_vigente(escalado, consulta, 1)


def test_g11_datos_sensibles_nunca_cumple_automatico(bd, coordinador, tmp_path):
    importar_diario(bd, coordinador, [ticket(5, d(1), "Tecnico 01", "Baja")], d(1), d(1, 23), tmp_path)
    importar_seguimientos(bd, coordinador, [], d(1, 23), tmp_path,
                          filas=[nota(5, d(1, 11), "Se entregó la clave: 1234 al operador")])
    resultado = cal.precalificar(bd, 5, "GESTION", ahora=d(2))["G-11"]
    assert resultado.resultado == cal.NO_CUMPLE and "Revisar" in resultado.nota


def test_sin_seguimientos_solo_reglas_del_ticket(bd, coordinador, tmp_path):
    importar_diario(bd, coordinador, [ticket(6, d(1), "Tecnico 01", "Baja", (d(2), gen.CERRADO))], d(1), d(2, 23), tmp_path)
    automaticos = cal.precalificar(bd, 6, "GESTION", ahora=d(3))
    assert set(automaticos) == {"G-02", "G-07", "G-10"}
    assert automaticos["G-10"].resultado == cal.CUMPLE


def test_p1_actualizaciones_cada_60_minutos(bd, coordinador, tmp_path):
    importar_diario(bd, coordinador, [ticket(7, d(1, 8), "Tecnico 01", "Mayor", (d(1, 12), gen.RESUELTO))],
                    d(1), d(1, 23), tmp_path)
    notas = [nota(7, d(1, 8, 5), "[P1-INICIO] 08:05\nDetección: 08:00\nAviso: coordinador 08:06"),
             nota(7, d(1, 9), "[P1-ACT] 09:00"), nota(7, d(1, 10, 30), "[P1-ACT] 10:30"),
             nota(7, d(1, 11, 20), "[P1-RESTABLECIDO] 11:20")]
    importar_seguimientos(bd, coordinador, [], d(1, 23), tmp_path, filas=notas)
    automaticos = cal.precalificar(bd, 7, "CRITICO_P1", ahora=d(2))
    assert automaticos["P-01"].resultado == cal.CUMPLE
    assert automaticos["P-02"].resultado == cal.NO_CUMPLE and "90 min" in automaticos["P-02"].nota
