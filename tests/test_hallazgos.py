"""Hallazgos automáticos HAL-01 a HAL-12 (CA-10, CA-11) y estado SLA por ticket."""

from datetime import datetime, timedelta

import pytest

import generador_glpi as gen
from ayudas import importar_diario, ticket
from core import clasificacion as cl
from core import historial, seguridad
from core.analisis import hallazgos as hal
from core.analisis import sla
from core.errores import ErrorPermiso, ErrorValidacion


def d(dia, hora=10, mes=9):
    return datetime(2026, mes, dia, hora, 0)


def con_titulo(t, titulo):
    t.titulo = titulo
    return t


def hallazgos_de(bd, regla):
    return bd.execute("SELECT * FROM hallazgo WHERE regla = ? ORDER BY id", (regla,)).fetchall()


def datos_de(fila):
    import json
    return json.loads(fila["datos_json"])


# --- CA-10: caso repetido ---

@pytest.fixture
def repetidos(bd, coordinador, tmp_path):
    # Semana 38 (lunes 14 a domingo 20 de septiembre): 4 «represamiento» en Norte
    titulos = ["Represamiento de datos carril 1", "REPRESAMIENTO de datos carril 2",
               "Represamiento de datos carril 3", "Represamiento de datos carril 9"]
    tickets = [con_titulo(ticket(100 + i, d(14 + 2 * i), "Tecnico 01", "Mediana"), t) for i, t in enumerate(titulos)]
    tickets.append(con_titulo(ticket(200, d(15), "Tecnico 01", "Mediana"), "Represamiento de datos carril 4"))
    importar_diario(bd, coordinador, tickets, d(14), d(20, 23), tmp_path)
    norte = cl.guardar_estacion(bd, coordinador, nombre="Norte")
    sur = cl.guardar_estacion(bd, coordinador, nombre="Sur")
    cl.clasificar(bd, coordinador, [100, 101, 102, 103], {cl.ESTACION: norte})
    cl.clasificar(bd, coordinador, [200], {cl.ESTACION: sur})
    return bd


def test_ca10_caso_repetido_con_sus_4_tickets(repetidos):
    hal.detectar(repetidos, ahora=d(21, 8))
    filas = hallazgos_de(repetidos, "HAL-01")
    semanales = [f for f in filas if f["periodo"] == "2026-W38"]
    assert len(semanales) == 1
    fila = semanales[0]
    assert (fila["severidad"], fila["entidad_valor"]) == ("MEDIA", "Norte | represamiento de datos carril")
    assert datos_de(fila)["tickets"] == [100, 101, 102, 103]
    assert "Evaluar Problema en GLPI" in fila["descripcion"]
    assert not [f for f in filas if f["periodo"] == "2026-09"]  # 4 < 5 en el mes


def test_ca10_reimportar_y_volver_a_detectar_no_duplica(repetidos, coordinador, tmp_path):
    hal.detectar(repetidos, ahora=d(21, 8))
    extra = ticket(300, d(21), "Tecnico 02", "Baja")
    importar_diario(repetidos, coordinador, [extra], d(21), d(21, 23), tmp_path / "otra")
    resumen = hal.detectar(repetidos, ahora=d(21, 23))
    assert len([f for f in hallazgos_de(repetidos, "HAL-01") if f["periodo"] == "2026-W38"]) == 1
    assert resumen.actualizados >= 1


# --- CA-11: sin seguimiento ---

def test_ca11_ticket_alta_sin_seguimiento_hace_5_horas(bd, coordinador, tmp_path):
    tickets = [ticket(1, d(18, 7), "Tecnico 01", "Urgente"), ticket(2, d(18, 7), "Tecnico 01", "Mediana")]
    importar_diario(bd, coordinador, tickets, d(18), d(18, 23), tmp_path)
    hal.detectar(bd, ahora=d(18, 12))
    filas = hallazgos_de(bd, "HAL-04")
    assert [(f["entidad_valor"], f["severidad"]) for f in filas] == [("1", "ALTA")]
    assert "5.0 h sin actualización" in filas[0]["descripcion"]


# --- Situación actual: se cierra sola ---

def test_p1_abierto_se_cierra_al_resolverse(bd, coordinador, tmp_path):
    p1 = ticket(1, d(10), "Tecnico 01", "Mayor", (d(12), gen.RESUELTO))
    importar_diario(bd, coordinador, [p1], d(10), d(10, 23), tmp_path)
    hal.detectar(bd, ahora=d(11))
    assert hallazgos_de(bd, "HAL-07")[0]["estado"] == "NUEVO"
    importar_diario(bd, coordinador, [p1], d(12), d(12, 23), tmp_path / "b")
    resumen = hal.detectar(bd, ahora=d(12, 23))
    assert hallazgos_de(bd, "HAL-07")[0]["estado"] == "CERRADO" and resumen.cerrados >= 1


def test_escalado_estancado_media_y_alta(bd, coordinador, tmp_path):
    tickets = [
        ticket(1, d(1), "Tecnico 01", "Baja", (d(2), gen.ESCALADO)),
        ticket(2, d(1), "Tecnico 01", "Baja", (d(8), gen.ESCALADO)),
    ]
    importar_diario(bd, coordinador, tickets, d(1), d(8, 23), tmp_path)
    hal.detectar(bd, ahora=d(14))
    assert {(f["entidad_valor"], f["severidad"]) for f in hallazgos_de(bd, "HAL-06")} == {("1", "ALTA"), ("2", "MEDIA")}


def test_resuelto_sin_cerrar_agrupado_por_tecnico(bd, coordinador, tmp_path):
    tickets = [ticket(i, d(1), "Tecnico 01", "Baja", (d(2), gen.RESUELTO)) for i in (1, 2)]
    importar_diario(bd, coordinador, tickets, d(1), d(2, 23), tmp_path)
    hal.detectar(bd, ahora=d(10))
    fila = hallazgos_de(bd, "HAL-05")[0]
    assert (fila["entidad_valor"], datos_de(fila)["conteo"], fila["severidad"]) == ("Tecnico 01", 2, "BAJA")


def test_sobrecarga_de_tecnico(bd, coordinador, tmp_path):
    tickets = [ticket(i, d(1, 8 + i), f"Tecnico 0{i}", "Baja") for i in (1, 2, 3)]
    tickets += [ticket(10 + i, d(1, 12), "Tecnico 04", "Baja") for i in range(6)]
    importar_diario(bd, coordinador, tickets, d(1), d(1, 23), tmp_path)
    hal.detectar(bd, ahora=d(1, 23))
    assert [f["entidad_valor"] for f in hallazgos_de(bd, "HAL-08")] == ["Tecnico 04"]


# --- Por período ---

def test_pico_por_estacion(bd, coordinador, tmp_path):
    base = [ticket(i, datetime(2026, 7, 20, 10) + timedelta(weeks=i), "Tecnico 01", "Baja") for i in range(8)]
    pico = [ticket(100 + i, d(14 + i % 5, 9 + i), "Tecnico 01", "Baja") for i in range(6)]
    importar_diario(bd, coordinador, base + pico, datetime(2026, 7, 20), d(20, 23), tmp_path)
    norte = cl.guardar_estacion(bd, coordinador, nombre="Norte")
    cl.clasificar(bd, coordinador, [t.id_glpi for t in base + pico], {cl.ESTACION: norte})
    hal.detectar(bd, ahora=d(21, 8))
    filas = hallazgos_de(bd, "HAL-02")
    assert [(f["entidad_valor"], f["periodo"], f["severidad"]) for f in filas] == [("Norte", "2026-W38", "ALTA")]
    assert len(datos_de(filas[0])["tickets"]) == 6


def test_categoria_en_crecimiento(bd, coordinador, tmp_path):
    previos = [ticket(i, datetime(2026, 6 + i, 10, 10), "Tecnico 01", "Baja") for i in range(3)]
    actuales = [ticket(10 + i, d(1 + i), "Tecnico 01", "Baja") for i in range(6)]
    importar_diario(bd, coordinador, previos + actuales, datetime(2026, 6, 10), d(6, 23), tmp_path)
    cl.clasificar(bd, coordinador, [t.id_glpi for t in previos + actuales], {cl.CATEGORIA: "DAT-02"})
    hal.detectar(bd, ahora=d(7))
    fila = hallazgos_de(bd, "HAL-03")[0]
    assert (fila["entidad_valor"], fila["periodo"], datos_de(fila)["conteo"]) == ("DAT-02", "2026-09", 6)


def test_tickets_resueltos_sin_clasificar(bd, coordinador, tmp_path):
    tickets = [ticket(1, d(14), "Tecnico 01", "Baja", (d(15), gen.RESUELTO)),
               ticket(2, d(14), "Tecnico 01", "Baja", (d(15), gen.RESUELTO))]
    importar_diario(bd, coordinador, tickets, d(14), d(15, 23), tmp_path)
    cl.guardar_estacion(bd, coordinador, nombre="Norte")
    cl.clasificar(bd, coordinador, [1], {cl.ESTACION: 1, cl.CATEGORIA: "APL-01", cl.CAUSA: "CAU-01",
                                         cl.TIPO_SOLUCION: "SOL-01"})
    hal.detectar(bd, ahora=d(16))
    fila = hallazgos_de(bd, "HAL-09")[0]
    assert (fila["severidad"], datos_de(fila)["tickets"]) == ("BAJA", [2])


def test_semaforo_en_rojo_y_reapertura(bd, coordinador, tmp_path):
    tickets = [ticket(1, d(1), "Tecnico 01", "Baja", (d(2), gen.ESCALADO)),
               ticket(2, d(1), "Tecnico 01", "Baja", (d(2), gen.RESUELTO), (d(3), gen.ASIGNADO))]
    importar_diario(bd, coordinador, tickets, d(1), d(3, 23), tmp_path)
    hal.detectar(bd, ahora=d(4))
    rojos = {f["entidad_valor"] for f in hallazgos_de(bd, "HAL-10") if f["periodo"] == "2026-09"}
    assert "KPI-05" in rojos  # 1 escalamiento de 2 gestiones = 50 %
    assert [f["entidad_valor"] for f in hallazgos_de(bd, "HAL-11")] == ["2"]


def test_importacion_desactualizada(bd, coordinador, tmp_path):
    hal.detectar(bd, ahora=d(1))
    assert hallazgos_de(bd, "HAL-12")[0]["estado"] == "NUEVO"
    importar_diario(bd, coordinador, [ticket(1, d(1), "Tecnico 01", "Baja")], d(1), d(1, 23), tmp_path)
    from core.importacion import carga
    hal.detectar(bd, ahora=carga.ultima_importacion(bd) + timedelta(hours=1))
    assert hallazgos_de(bd, "HAL-12")[0]["estado"] == "CERRADO"


# --- Revisión y permisos ---

def test_revisar_descartar_y_se_respeta_al_redetectar(repetidos, coordinador):
    hal.detectar(repetidos, ahora=d(21, 8))
    fila = [f for f in hallazgos_de(repetidos, "HAL-01") if f["periodo"] == "2026-W38"][0]
    with pytest.raises(ErrorValidacion, match="comentario"):
        hal.revisar(repetidos, coordinador, fila["id"], hal.DESCARTADO, " ")
    hal.revisar(repetidos, coordinador, fila["id"], hal.DESCARTADO, "Ya hay un Problema abierto en GLPI")
    hal.detectar(repetidos, ahora=d(21, 9))
    assert repetidos.execute("SELECT estado FROM hallazgo WHERE id = ?", (fila["id"],)).fetchone()[0] == "DESCARTADO"
    registro = historial.consultar(repetidos, entidad="hallazgo")[0]
    assert (registro["valor_nuevo"], registro["nota"]) == ("DESCARTADO", "Ya hay un Problema abierto en GLPI")
    assert hal.tickets_de(repetidos, fila["id"]) == [100, 101, 102, 103]


def test_consulta_no_revisa_ni_ve_hallazgos_de_tecnicos(bd, coordinador, tmp_path):
    tickets = [ticket(1, d(1), "Tecnico 01", "Mayor"), ticket(2, d(1), "Tecnico 01", "Baja", (d(2), gen.RESUELTO))]
    importar_diario(bd, coordinador, tickets, d(1), d(2, 23), tmp_path)
    hal.detectar(bd, ahora=d(10))
    usuario = seguridad.crear_usuario(bd, coordinador, nombre="Jefe", perfil=seguridad.CONSULTA, pin="3333")
    jefe = seguridad.iniciar_sesion(bd, usuario, "3333")
    visibles = hal.listar(bd, jefe)
    assert not visibles["Regla"].str.startswith(("HAL-04", "HAL-05", "HAL-07")).any()
    assert hal.listar(bd, coordinador)["Regla"].str.startswith("HAL-07").any()
    with pytest.raises(ErrorPermiso):
        hal.revisar(bd, jefe, 1, hal.REVISADO, "")
    assert hal.conteo_nuevos(bd, coordinador)["ALTA"] >= 1


# --- Estado SLA por ticket ---

@pytest.mark.parametrize(
    "solucion, objetivo, ahora, esperado",
    [
        (d(1, 20), 24, d(5), "CUMPLIDO"),
        (d(3), 24, d(5), "INCUMPLIDO"),
        (None, 24, d(1, 20), "EN_PLAZO"),
        (None, 24, d(2, 6), "EN_RIESGO"),   # 20 h de 24 h = 83 %
        (None, 24, d(2, 12), "INCUMPLIDO"),
        (None, None, d(2), "SIN_OBJETIVO"),
    ],
)
def test_estado_sla(solucion, objetivo, ahora, esperado):
    estado, _ = sla.estado(d(1), solucion, objetivo, ahora, 80)
    assert estado == esperado
