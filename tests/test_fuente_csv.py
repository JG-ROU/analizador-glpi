from datetime import datetime

import pandas as pd
import pytest

import generador_glpi as gen
from core.errores import ErrorAplicacion, ErrorValidacion
from core.fuentes.base import COLUMNA_FILA, FuenteDatos
from core.fuentes.fuente_csv import (
    FormatoCSV,
    FuenteCSV,
    detectar_codificacion,
    detectar_formato_fecha,
    detectar_separador,
)

DESDE = datetime(2026, 8, 1)
HASTA = datetime(2026, 9, 23, 23, 59)
CORTE = datetime(2026, 9, 23, 7, 0)
LINEA_REAL = (
    '"ID";"Título";"Entidad";"Estado";"Autor - Autor";"Asignado a: - Técnico";'
    '"Fecha de Apertura";"Última actualización";"Prioridad";"Ubicación";\n'
    '"346 649";"TITULO DE NOVEDAD";"Grupo > Empresa > seccional > Departamento (ti)) > '
    'Area(Soporte/desarrollo/qa)";"En curso (asignada)";"Autor 1";"Tecnico 1";'
    '"06-04-2026 05:21";"22-09-2026 14:22";"Mediana";"Departamento (ti) > filial > cliente > estacion";\n'
)


def escribir(tmp_path, contenido, nombre="glpi.csv", codificacion="utf-8"):
    ruta = tmp_path / nombre
    if isinstance(contenido, str):
        contenido = contenido.encode(codificacion)
    ruta.write_bytes(contenido)
    return ruta


def exportacion(tmp_path, cantidad=300, **opciones):
    tickets = gen.generar_tickets(cantidad, DESDE, HASTA, semilla=11)
    filas = gen.filas_en(tickets, CORTE)
    return gen.escribir_csv(filas, tmp_path / "glpi.csv", **opciones), filas


# --- Formato real del usuario (IMP-00) ---

def test_linea_real_del_usuario(tmp_path):
    fuente = FuenteCSV(escribir(tmp_path, LINEA_REAL))
    formato = fuente.formato
    assert formato.separador == ";"
    assert formato.codificacion == "utf-8"
    assert formato.encabezados == gen.ENCABEZADOS
    assert formato.formato_fecha == "%d-%m-%Y %H:%M"
    assert formato.columnas_fecha == ("Fecha de Apertura", "Última actualización")
    assert not formato.fecha_ambigua
    filas = pd.concat(list(fuente.obtener_tickets()))
    assert list(filas.columns) == [COLUMNA_FILA, *gen.ENCABEZADOS]
    assert filas.iloc[0]["ID"] == "346 649"
    assert filas.iloc[0]["Asignado a: - Técnico"] == "Tecnico 1"
    assert filas.iloc[0][COLUMNA_FILA] == 2


def test_es_una_fuente_de_datos(tmp_path):
    assert isinstance(FuenteCSV(escribir(tmp_path, LINEA_REAL)), FuenteDatos)


def test_exportacion_completa_generada(tmp_path):
    ruta, filas = exportacion(tmp_path)
    leidas = pd.concat(list(FuenteCSV(ruta).obtener_tickets()))
    assert len(leidas) == len(filas)
    assert leidas["Título"].tolist() == [f["titulo"] for f in filas]
    multiples = leidas[leidas["Asignado a: - Técnico"].str.contains("\n")]
    assert not multiples.empty
    assert (leidas.map(lambda v: isinstance(v, (str, int)))).all().all()


def test_numero_de_fila_cuenta_registros_aunque_haya_celdas_multilinea(tmp_path):
    ruta, filas = exportacion(tmp_path, cantidad=120)
    leidas = pd.concat(list(FuenteCSV(ruta, tamano_bloque=25).obtener_tickets()))
    assert leidas[COLUMNA_FILA].tolist() == list(range(2, len(filas) + 2))


def test_lectura_por_bloques(tmp_path):
    ruta, filas = exportacion(tmp_path, cantidad=120)
    bloques = list(FuenteCSV(ruta, tamano_bloque=25).obtener_tickets())
    assert len(bloques) == -(-len(filas) // 25)
    assert all(len(b) <= 25 for b in bloques)
    assert all(b.index[0] == 0 for b in bloques)


def test_hash_del_archivo(tmp_path):
    ruta, _ = exportacion(tmp_path)
    copia = escribir(tmp_path, ruta.read_bytes(), "copia.csv")
    assert FuenteCSV(ruta).hash == FuenteCSV(copia).hash
    assert len(FuenteCSV(ruta).hash) == 64
    distinto = escribir(tmp_path, ruta.read_bytes() + b"\n", "distinto.csv")
    assert FuenteCSV(distinto).hash != FuenteCSV(ruta).hash


# --- Codificación ---

@pytest.mark.parametrize(
    "codificacion, esperada", [("utf-8", "utf-8"), ("utf-8-sig", "utf-8-sig"), ("cp1252", "cp1252")]
)
def test_codificaciones(tmp_path, codificacion, esperada):
    ruta, _ = exportacion(tmp_path, cantidad=30, codificacion=codificacion)
    fuente = FuenteCSV(ruta)
    assert fuente.formato.codificacion == esperada
    assert fuente.formato.encabezados[1] == "Título"
    assert fuente.muestra(5)["Ubicación"].str.contains("Estación").all()


def test_detectar_codificacion():
    assert detectar_codificacion("Título".encode("utf-8")) == "utf-8"
    assert detectar_codificacion(b"\xef\xbb\xbfID") == "utf-8-sig"
    assert detectar_codificacion("Título".encode("latin-1")) == "cp1252"


def test_codificacion_equivocada_en_el_perfil(tmp_path):
    ruta, _ = exportacion(tmp_path, cantidad=30, codificacion="cp1252")
    detectado = FuenteCSV(ruta).formato
    forzado = FormatoCSV("utf-8", detectado.separador, detectado.encabezados)
    with pytest.raises(ErrorValidacion, match="codificación"):
        list(FuenteCSV(ruta, formato=forzado).obtener_tickets())


# --- Separador y encabezados ---

def test_separador_coma(tmp_path):
    texto = LINEA_REAL.replace('";"', '","').replace('";\n', '",\n')
    fuente = FuenteCSV(escribir(tmp_path, texto))
    assert fuente.formato.separador == ","
    assert fuente.muestra(1).iloc[0]["Prioridad"] == "Mediana"


def test_detectar_separador_ignora_lo_que_esta_entre_comillas():
    assert detectar_separador('"a,b,c";"d,e";"f"') == ";"
    with pytest.raises(ErrorValidacion, match="separador"):
        detectar_separador('"una sola columna"')


def test_sin_punto_y_coma_final(tmp_path):
    texto = LINEA_REAL.replace('";\n', '"\n')
    fuente = FuenteCSV(escribir(tmp_path, texto))
    assert fuente.formato.encabezados == gen.ENCABEZADOS
    assert fuente.muestra(1).iloc[0]["Ubicación"].endswith("estacion")


def test_fila_incompleta_se_completa_con_vacios(tmp_path):
    texto = LINEA_REAL + '"346 650";"Corta";"Entidad"\n'
    filas = pd.concat(list(FuenteCSV(escribir(tmp_path, texto)).obtener_tickets()))
    assert filas.iloc[1]["Prioridad"] == ""
    assert filas.iloc[1][COLUMNA_FILA] == 3


def test_lineas_en_blanco_se_ignoran(tmp_path):
    fuente = FuenteCSV(escribir(tmp_path, LINEA_REAL + "\n\n"))
    assert len(pd.concat(list(fuente.obtener_tickets()))) == 1


def test_encabezados_repetidos(tmp_path):
    with pytest.raises(ErrorValidacion, match="repetidos: ID"):
        FuenteCSV(escribir(tmp_path, '"ID";"ID";"Estado";\n"1";"2";"x";\n'))


def test_encabezado_vacio_en_medio(tmp_path):
    with pytest.raises(ErrorValidacion, match="columna 2"):
        FuenteCSV(escribir(tmp_path, '"ID";"";"Estado";\n"1";"2";"x";\n'))


def test_archivo_vacio(tmp_path):
    with pytest.raises(ErrorValidacion, match="vacío"):
        FuenteCSV(escribir(tmp_path, "  \n"))


def test_archivo_inexistente(tmp_path):
    with pytest.raises(ErrorAplicacion, match="No se pudo leer"):
        FuenteCSV(tmp_path / "no_existe.csv")


def test_encabezados_distintos_al_formato_del_perfil(tmp_path):
    fuente = FuenteCSV(escribir(tmp_path, LINEA_REAL))
    otro = FormatoCSV("utf-8", ";", ("ID", "Otro"))
    with pytest.raises(ErrorValidacion, match="no coinciden"):
        list(FuenteCSV(fuente.ruta, formato=otro).obtener_tickets())


def test_seguimientos_llegan_en_fase_3(tmp_path):
    with pytest.raises(ErrorAplicacion, match="Fase 3"):
        FuenteCSV(escribir(tmp_path, LINEA_REAL)).obtener_seguimientos([1])


# --- Formato de fecha ---

def muestra_con(*fechas):
    return pd.DataFrame({"Fecha": list(fechas), "Otra": ["texto"] * len(fechas)})


@pytest.mark.parametrize(
    "fechas, esperado",
    [
        (("06-04-2026 05:21", "22-09-2026 14:22"), "%d-%m-%Y %H:%M"),
        (("6/04/2026 5:21", "22/09/2026 14:22"), "%d/%m/%Y %H:%M"),
        (("2026-04-06 05:21", "2026-09-22 14:22"), "%Y-%m-%d %H:%M"),
        (("2026-04-06 05:21:10", "2026-09-22 14:22:00"), "%Y-%m-%d %H:%M:%S"),
        (("04-06-2026 05:21", "09-22-2026 14:22"), "%m-%d-%Y %H:%M"),
    ],
)
def test_detectar_formato_fecha(fechas, esperado):
    formato, columnas, ambigua = detectar_formato_fecha(muestra_con(*fechas))
    assert formato == esperado
    assert columnas == ("Fecha",)
    assert not ambigua


def test_fecha_ambigua_prefiere_dia_antes_que_mes():
    formato, _, ambigua = detectar_formato_fecha(muestra_con("06-04-2026 05:21", "01-02-2026 10:00"))
    assert formato == "%d-%m-%Y %H:%M"
    assert ambigua


def test_columna_con_pocas_fechas_no_es_de_fecha():
    muestra = pd.DataFrame({"Título": ["01-02-2026 10:00 falla", "texto", "otro", "más", "x"]})
    assert detectar_formato_fecha(muestra) == (None, (), False)


def test_celdas_vacias_no_impiden_detectar_fechas():
    formato, columnas, _ = detectar_formato_fecha(muestra_con("22-09-2026 14:22", "", "23-09-2026 08:00"))
    assert formato == "%d-%m-%Y %H:%M" and columnas == ("Fecha",)
