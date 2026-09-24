"""Clasificación manual (IMP-07, CA-23), migración 002, catálogos y KPI-09 a KPI-12."""

import shutil
from datetime import datetime

import pytest

import generador_glpi as gen
from ayudas import importar_diario, ticket
from core import clasificacion as cl
from core import historial
from core.analisis import periodos
from core.analisis.filtros import Filtros
from core.analisis.kpis import CalculadoraKPI
from core.db import conexion as conexion_db, migrador, semilla
from core.errores import ErrorPermiso, ErrorValidacion
from core.texto import normalizar_titulo, ultimo_nivel

SEPTIEMBRE = periodos.mes(2026, 9)
AHORA = datetime(2026, 10, 5, 12, 0)


def d(dia, hora=10):
    return datetime(2026, 9, dia, hora, 0)


def con_ubicacion(t, ubicacion):
    t.ubicacion = ubicacion
    return t


@pytest.fixture
def datos(bd, coordinador, tmp_path):
    tickets = [
        con_ubicacion(ticket(1, d(1), "Tecnico 01", "Mediana", (d(2), gen.RESUELTO)), "Depto > Filial > Cliente A > Estación Norte"),
        con_ubicacion(ticket(2, d(3), "Tecnico 01", "Mediana", (d(4), gen.RESUELTO)), "Depto > Filial > Cliente A > ESTACION NORTE "),
        con_ubicacion(ticket(3, d(5), "Tecnico 02", "Baja", (d(6), gen.RESUELTO)), "Depto > Filial > Cliente B > Estación Sur"),
        con_ubicacion(ticket(4, d(7), "Tecnico 02", "Baja"), "Depto > Otra"),
    ]
    importar_diario(bd, coordinador, tickets, d(1), d(8, 23), tmp_path)
    norte = cl.guardar_estacion(bd, coordinador, nombre="Estación Norte", cliente="Cliente A")
    sur = cl.guardar_estacion(bd, coordinador, nombre="Estación Sur", cliente="Cliente B", incluir_segmov=False)
    return bd, norte, sur


def clasif(bd, ticket_id):
    return bd.execute("SELECT * FROM ticket_clasificacion WHERE ticket_id = ?", (ticket_id,)).fetchone()


# --- Migración y catálogos ---

def test_migracion_002_sobre_bd_de_fase_1_con_datos(tmp_path):
    solo_001 = tmp_path / "migraciones_fase1"
    solo_001.mkdir()
    shutil.copy(migrador.CARPETA_MIGRACIONES / "001_inicial.sql", solo_001)
    conexion = conexion_db.conectar(tmp_path / "analizador.db")
    migrador.migrar(conexion, tmp_path / "respaldos", solo_001)
    with conexion:
        conexion.execute("INSERT INTO festivo (fecha, descripcion) VALUES ('2026-12-25', 'Navidad')")
    assert migrador.migrar(conexion, tmp_path / "respaldos") == migrador.descubrir()[-1].version
    semilla.sembrar(conexion)
    assert conexion.execute("SELECT COUNT(*) FROM festivo").fetchone()[0] == 1
    assert list((tmp_path / "respaldos").glob("analizador_antes_migracion_v1_*.db"))
    conexion.close()


def test_catalogos_sembrados(bd):
    assert bd.execute("SELECT COUNT(*) FROM categoria").fetchone()[0] == 62
    assert bd.execute("SELECT COUNT(*) FROM causa").fetchone()[0] == 10
    assert bd.execute("SELECT COUNT(*) FROM tipo_solucion").fetchone()[0] == 11
    rec = bd.execute("SELECT * FROM categoria WHERE codigo = 'REC-03.1'").fetchone()
    assert (rec["familia"], rec["nivel3"]) == ("REC", "REC-03.1 Sobrecategorización")
    opciones = cl.opciones(bd, cl.CAUSA)
    assert opciones[0].valor == "CAU-01" and opciones[0].texto.startswith("CAU-01 Configuración")


# --- Estaciones ---

def test_estaciones_con_historial(datos, coordinador):
    bd, norte, _ = datos
    cl.guardar_estacion(bd, coordinador, nombre="Estación Norte", cliente="Cliente A2", estacion_id=norte)
    assert [(e["nombre"], e["cliente"]) for e in cl.listar_estaciones(bd)][0] == ("Estación Norte", "Cliente A2")
    registro = historial.consultar(bd, entidad="estacion")[0]
    assert (registro["campo"], registro["valor_nuevo"]) == ("cliente", "Cliente A2")
    with pytest.raises(ErrorValidacion, match="Ya existe"):
        cl.guardar_estacion(bd, coordinador, nombre="Estación Sur")


# --- Clasificación (CA-23) ---

def test_clasificar_varios_tickets_y_historial(datos, coordinador):
    bd, norte, _ = datos
    cambiados = cl.clasificar(bd, coordinador, [1, 2], {
        cl.ESTACION: norte, cl.CATEGORIA: "DAT-01", cl.CAUSA: "CAU-05", cl.TIPO_SOLUCION: "SOL-01",
    })
    assert cambiados == 2
    fila = clasif(bd, 1)
    assert (fila["estacion_id"], fila["categoria_codigo"], fila["causa_codigo"]) == (norte, "DAT-01", "CAU-05")
    registros = historial.consultar(bd, entidad="ticket_clasificacion", entidad_id=1)
    assert {r["campo"] for r in registros} == {"Estación", "Categoría", "Causa", "Tipo de solución"}
    categoria = next(r for r in registros if r["campo"] == "Categoría")
    assert categoria["valor_nuevo"] == "DAT-01 DAT-01 Represamiento de información"


def test_cambiar_solo_un_campo_y_sin_cambios(datos, coordinador):
    bd, norte, sur = datos
    cl.clasificar(bd, coordinador, [1], {cl.ESTACION: norte, cl.CATEGORIA: "APL-01"})
    assert cl.clasificar(bd, coordinador, [1], {cl.ESTACION: norte}) == 0
    cl.clasificar(bd, coordinador, [1], {cl.ESTACION: sur})
    assert clasif(bd, 1)["categoria_codigo"] == "APL-01"
    ultimo = historial.consultar(bd, entidad="ticket_clasificacion", entidad_id=1)[0]
    assert (ultimo["valor_anterior"], ultimo["valor_nuevo"]) == ("Estación Norte", "Estación Sur")
    cl.clasificar(bd, coordinador, [1], {cl.CATEGORIA: None})
    assert clasif(bd, 1)["categoria_codigo"] is None


def test_ca23_la_reimportacion_conserva_la_clasificacion(datos, coordinador, tmp_path):
    bd, norte, _ = datos
    cl.clasificar(bd, coordinador, [4], {cl.ESTACION: norte, cl.CATEGORIA: "RED-01"})
    cambia = ticket(4, d(7), "Tecnico 03", "Urgente", (d(9), gen.RESUELTO))
    importar_diario(bd, coordinador, [cambia], d(9), d(9, 23), tmp_path / "otra")
    assert bd.execute("SELECT estado_codigo FROM ticket WHERE id_glpi = 4").fetchone()[0] == "RESUELTO"
    assert (clasif(bd, 4)["estacion_id"], clasif(bd, 4)["categoria_codigo"]) == (norte, "RED-01")


@pytest.mark.parametrize(
    "cambios, mensaje",
    [({cl.CATEGORIA: "XXX-99"}, "no existe en el catálogo"), ({"prioridad": 3}, "desconocidos")],
)
def test_valores_invalidos(datos, coordinador, cambios, mensaje):
    with pytest.raises(ErrorValidacion, match=mensaje):
        cl.clasificar(datos[0], coordinador, [1], cambios)


def test_ticket_inexistente_no_deja_nada_a_medias(datos, coordinador):
    bd, norte, _ = datos
    with pytest.raises(ErrorValidacion, match="no existe"):
        cl.clasificar(bd, coordinador, [1, 999], {cl.ESTACION: norte})
    assert clasif(bd, 1) is None


def test_consulta_no_clasifica(datos, consulta):
    with pytest.raises(ErrorPermiso):
        cl.clasificar(datos[0], consulta, [1], {cl.CATEGORIA: "APL-01"})


def test_sugerir_estaciones_desde_ubicacion(datos, coordinador):
    bd, norte, sur = datos
    cl.clasificar(bd, coordinador, [3], {cl.ESTACION: norte})
    assert cl.sugerir_estaciones(bd, [1, 2, 3, 4]) == {1: norte, 2: norte}


def test_listar_pendientes(datos, coordinador):
    bd, norte, _ = datos
    cl.clasificar(bd, coordinador, [1], {cl.ESTACION: norte, cl.CATEGORIA: "APL-01", cl.CAUSA: "CAU-01",
                                         cl.TIPO_SOLUCION: "SOL-01"})
    pendientes = cl.listar(bd, coordinador, SEPTIEMBRE)
    assert sorted(pendientes["ID"]) == [2, 3, 4]
    assert list(pendientes["ID"])[-1] == 4  # los abiertos al final
    todos = cl.listar(bd, coordinador, SEPTIEMBRE, cl.TODOS)
    assert len(todos) == 4 and todos[todos["ID"] == 1].iloc[0]["Pendiente"] == "No"


# --- Texto ---

def test_normalizar_titulo_y_ultimo_nivel():
    assert normalizar_titulo("Falla en carril 3 – Estación Norte") == normalizar_titulo("falla en CARRIL 5 estacion norte")
    assert normalizar_titulo("Falla en carril 3 – Estación Norte") == "falla en carril estacion norte"
    assert ultimo_nivel("A > B >C ") == "C" and ultimo_nivel("") is None


# --- KPI-09 a KPI-12 y filtros ---

def test_kpi09_completitud(datos, coordinador):
    bd, norte, _ = datos
    cl.clasificar(bd, coordinador, [1], {cl.ESTACION: norte, cl.CATEGORIA: "APL-01", cl.CAUSA: "CAU-01",
                                         cl.TIPO_SOLUCION: "SOL-01"})
    cl.clasificar(bd, coordinador, [2], {cl.ESTACION: norte, cl.CATEGORIA: "APL-01"})
    kpi = CalculadoraKPI(bd, coordinador, AHORA).calcular("KPI-09", SEPTIEMBRE)
    assert (kpi.numerador, kpi.denominador) == (1, 3) and kpi.valor == 33.33


def test_kpi10_uso_de_otros(datos, coordinador):
    bd, _, _ = datos
    cl.clasificar(bd, coordinador, [1, 2, 3], {cl.CATEGORIA: "APL-01"})
    cl.clasificar(bd, coordinador, [4], {cl.CATEGORIA: "OTR-01"})
    kpi = CalculadoraKPI(bd, coordinador, AHORA).calcular("KPI-10", SEPTIEMBRE)
    assert (kpi.numerador, kpi.denominador, kpi.valor) == (1, 4, 25.0)


def test_kpi11_reincidencia(bd, coordinador, tmp_path):
    def con_titulo(t, titulo):
        t.titulo = titulo
        return t
    tickets = [
        con_titulo(ticket(1, d(1), "Tecnico 01", "Baja"), "Represamiento de datos carril 2"),
        con_titulo(ticket(2, d(3), "Tecnico 01", "Baja"), "REPRESAMIENTO de datos carril 7"),
        con_titulo(ticket(3, d(20), "Tecnico 01", "Baja"), "Represamiento de datos"),
        con_titulo(ticket(4, d(4), "Tecnico 01", "Baja"), "Impresora sin papel"),
        con_titulo(ticket(5, d(2), "Tecnico 01", "Baja"), "Represamiento de datos"),
    ]
    importar_diario(bd, coordinador, tickets, d(1), d(20, 23), tmp_path)
    norte = cl.guardar_estacion(bd, coordinador, nombre="Norte")
    sur = cl.guardar_estacion(bd, coordinador, nombre="Sur")
    cl.clasificar(bd, coordinador, [1, 2, 3, 4], {cl.ESTACION: norte})
    cl.clasificar(bd, coordinador, [5], {cl.ESTACION: sur})
    kpi = CalculadoraKPI(bd, coordinador, AHORA).calcular("KPI-11", SEPTIEMBRE)
    # Solo el ticket 2 repite caso (Norte + «represamiento de datos carril») dentro de 7 días
    assert (kpi.numerador, kpi.denominador, kpi.valor) == (1, 5, 20.0)


def test_kpi12_reaperturas(bd, coordinador, tmp_path):
    tickets = [
        ticket(1, d(1), "Tecnico 01", "Baja", (d(2), gen.RESUELTO), (d(3), gen.ASIGNADO), (d(4), gen.RESUELTO)),
        ticket(2, d(1, 12), "Tecnico 01", "Baja", (d(2, 12), gen.RESUELTO)),
    ]
    importar_diario(bd, coordinador, tickets, d(1), d(5, 23), tmp_path)
    kpi = CalculadoraKPI(bd, coordinador, AHORA).calcular("KPI-12", SEPTIEMBRE)
    assert (kpi.numerador, kpi.denominador, kpi.valor) == (1, 2, 50.0)


def test_filtros_de_clasificacion(datos, coordinador):
    bd, norte, sur = datos
    cl.clasificar(bd, coordinador, [1, 2], {cl.ESTACION: norte, cl.CATEGORIA: "REC-03.1", cl.CAUSA: "CAU-02"})
    cl.clasificar(bd, coordinador, [3], {cl.ESTACION: sur, cl.CATEGORIA: "APL-01"})
    calc = CalculadoraKPI(bd, coordinador, AHORA)
    recibidos = lambda filtros: calc.calcular("KPI-01", SEPTIEMBRE, filtros, comparar=False).valor  # noqa: E731
    assert recibidos(Filtros(estaciones=(norte,))) == 2
    assert recibidos(Filtros(clientes=("Cliente B",))) == 1
    assert recibidos(Filtros(familias=("REC",))) == 2
    assert recibidos(Filtros(categorias=("APL-01",), estaciones=(sur,))) == 1
    assert recibidos(Filtros(causas=("CAU-02",), turno="Mañana")) == 2
    assert recibidos(Filtros(familias=("XXX",))) == 0
