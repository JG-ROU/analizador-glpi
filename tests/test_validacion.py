from datetime import datetime

import pandas as pd
import pytest

import generador_glpi as gen
from core.fuentes.base import COLUMNA_FILA
from core.fuentes.fuente_csv import FuenteCSV
from core.importacion import mapeo as m
from core.importacion import validacion as v

CORTE = datetime(2026, 9, 23, 7, 0)


def perfil(**cambios):
    base = m.PerfilImportacion(
        nombre="Prueba", separador=";", codificacion="utf-8", formato_fecha="%d-%m-%Y %H:%M",
        mapeo=m.Mapeo(columnas=m.proponer_columnas(gen.ENCABEZADOS)),
    )
    return m.replace(base, **cambios) if cambios else base


def fila(**valores):
    """Fila cruda válida del CSV real, con los cambios indicados."""
    base = {
        "ID": "346 649", "Título": "Novedad de prueba", "Entidad": "Grupo > Empresa",
        "Estado": "En curso (asignada)", "Autor - Autor": "Autor 1",
        "Asignado a: - Técnico": "Tecnico 1", "Fecha de Apertura": "06-04-2026 05:21",
        "Última actualización": "22-09-2026 14:22", "Prioridad": "Mediana",
        "Ubicación": "Departamento > Filial > Cliente > Estación",
    }
    base.update(valores)
    return base


def bloque(*filas, primera=2):
    datos = pd.DataFrame(list(filas), columns=list(gen.ENCABEZADOS))
    datos.insert(0, COLUMNA_FILA, range(primera, primera + len(datos)))
    return datos


def validar(*filas):
    return v.validar([bloque(*filas)], perfil())


# --- Interpretación ---

@pytest.mark.parametrize(
    "texto, esperado",
    [("346 649", 346649), ("346 649", 346649), ("346 649", 346649), ("649", 649),
     (" 1 234 567 ", 1234567), ("", None), ("34A 123", None), ("346.649", None), ("-5", None)],
)
def test_normalizar_id(texto, esperado):
    assert v.normalizar_id(texto) == esperado


def test_separar_tecnicos():
    assert v.separar_tecnicos("Tecnico 1\nTecnico 2", "\n") == ("Tecnico 1", "Tecnico 2")
    assert v.separar_tecnicos("Tecnico 1\n\n\nTecnico 2\n", "\n") == ("Tecnico 1", "Tecnico 2")
    assert v.separar_tecnicos("Tecnico 1\r\nTecnico  2\r\nTecnico 1", "\n") == ("Tecnico 1", "Tecnico 2")
    assert v.separar_tecnicos("  \n ", "\n") == ()
    assert v.separar_tecnicos("A, B", ",") == ("A", "B")


def test_formato_legible():
    assert v.formato_legible("%d-%m-%Y %H:%M") == "DD-MM-AAAA HH:MM"


# --- Resultados ---

def test_fila_valida_interpretada():
    resultado = validar(fila())
    dato = resultado.filas.iloc[0]
    assert dato["resultado"] == v.VALIDA and dato["motivos"] == ""
    assert dato["id_glpi"] == 346649
    assert dato["estado_codigo"] == "EN_CURSO_ASIGNADO"
    assert dato["prioridad_nivel"] == 3
    assert dato["tecnicos"] == ("Tecnico 1",)
    assert dato["fecha_apertura"] == datetime(2026, 4, 6, 5, 21)
    assert dato["ultima_actualizacion"] == datetime(2026, 9, 22, 14, 22)
    assert dato[COLUMNA_FILA] == 2


@pytest.mark.parametrize(
    "cambios, motivo",
    [
        ({"ID": ""}, "ID vacío"),
        ({"ID": "34A 123"}, "El ID «34A 123» no es numérico"),
        ({"Fecha de Apertura": "31-02-2026 10:00"},
         "Fecha de apertura inválida: «31-02-2026 10:00» (formato esperado DD-MM-AAAA HH:MM)"),
        ({"Fecha de Apertura": "2026-04-06 05:21"}, "Fecha de apertura inválida"),
        ({"Última actualización": ""}, "Última actualización vacía"),
        ({"Estado": "Pendiente de revisión"}, "Estado sin mapear: «Pendiente de revisión»"),
        ({"Estado": ""}, "Estado vacío"),
        ({"Prioridad": "Crítica"}, "Prioridad sin mapear: «Crítica»"),
        ({"Título": "   "}, "Título vacío"),
    ],
)
def test_errores_con_motivo(cambios, motivo):
    dato = validar(fila(**cambios)).filas.iloc[0]
    assert dato["resultado"] == v.ERROR
    assert motivo in dato["motivos"]


def test_varios_errores_en_la_misma_fila():
    dato = validar(fila(ID="", Estado="Raro")).filas.iloc[0]
    assert dato["motivos"] == (
        "ID vacío; Estado sin mapear: «Raro». Asócielo a un estado en el perfil de importación"
    )


@pytest.mark.parametrize(
    "cambios, motivo",
    [
        ({"Asignado a: - Técnico": ""}, "Sin técnico asignado"),
        ({"Última actualización": "01-04-2026 00:00"},
         "La última actualización es anterior a la fecha de apertura"),
    ],
)
def test_advertencias_se_cargan(cambios, motivo):
    resultado = validar(fila(**cambios))
    dato = resultado.filas.iloc[0]
    assert (dato["resultado"], dato["motivos"]) == (v.ADVERTENCIA, motivo)
    assert len(resultado.cargables) == 1


def test_id_repetido_entre_bloques_distintos():
    validador_bloques = [
        bloque(fila(ID="100"), fila(ID="101")),
        bloque(fila(ID="102"), fila(ID="100"), primera=4),
    ]
    resultado = v.validar(validador_bloques, perfil())
    assert resultado.filas["resultado"].tolist() == [v.VALIDA, v.VALIDA, v.VALIDA, v.ERROR]
    assert resultado.filas.iloc[3]["motivos"] == "ID repetido: ya aparece en la fila 2"


def test_id_con_formatos_distintos_se_reconoce_repetido():
    resultado = validar(fila(ID="346 649"), fila(ID="346649"))
    assert resultado.filas.iloc[1]["resultado"] == v.ERROR


def test_campos_opcionales_sin_mapear_quedan_vacios():
    columnas = {k: c for k, c in m.proponer_columnas(gen.ENCABEZADOS).items()
                if k not in ("entidad", "autor", "ubicacion")}
    resultado = v.validar([bloque(fila())], perfil(mapeo=m.Mapeo(columnas)))
    dato = resultado.filas.iloc[0]
    assert dato["resultado"] == v.VALIDA
    assert dato["entidad"] is None and dato["autor"] is None and dato["ubicacion"] is None


def test_estado_agregado_al_perfil_se_acepta():
    nuevo = m.Mapeo(
        columnas=m.proponer_columnas(gen.ENCABEZADOS),
        estados={**m.MAPEO_ESTADOS_GLPI, "Pendiente de revisión": "EN_ESPERA"},
    )
    resultado = v.validar([bloque(fila(Estado="Pendiente de revisión"))], perfil(mapeo=nuevo))
    assert resultado.filas.iloc[0]["estado_codigo"] == "EN_ESPERA"


# --- CA-03 con una exportación generada ---

def test_ca03_errores_no_se_cargan_y_el_resto_si(tmp_path):
    tickets = gen.generar_tickets(200, datetime(2026, 8, 1), datetime(2026, 9, 23), semilla=9)
    filas = gen.inyectar_errores(gen.filas_en(tickets, CORTE), 6)
    ruta = gen.escribir_csv(filas, tmp_path / "glpi.csv")
    fuente = FuenteCSV(ruta, tamano_bloque=50)
    resultado = v.validar(fuente.obtener_tickets(), m.proponer_perfil(fuente.formato))

    assert resultado.filas_leidas == len(filas)
    assert resultado.conteo(v.ERROR) == 6
    assert len(resultado.cargables) == len(filas) - 6
    titulos_con_error = set(resultado.con_error["titulo"])
    assert all(t.startswith("Fila con error") for t in titulos_con_error)
    motivos = " | ".join(resultado.con_error["motivos"])
    for esperado in ("inválida", "ID vacío", "no es numérico", "ID repetido",
                     "Estado sin mapear", "Prioridad sin mapear"):
        assert esperado in motivos
    sin_tecnico = sum(1 for f in filas if not f["tecnicos"] and "error" not in f)
    assert resultado.conteo(v.ADVERTENCIA) >= sin_tecnico


def test_rango_de_fechas_de_las_filas_cargables():
    resultado = validar(
        fila(ID="1", **{"Fecha de Apertura": "01-09-2026 08:00"}),
        fila(ID="2", **{"Fecha de Apertura": "15-09-2026 10:30"}),
        fila(ID="", **{"Fecha de Apertura": "01-01-2020 00:00"}),
    )
    assert resultado.rango_fechas == (datetime(2026, 9, 1, 8, 0), datetime(2026, 9, 15, 10, 30))


def test_archivo_sin_filas():
    resultado = v.validar([], perfil())
    assert resultado.filas_leidas == 0
    assert resultado.rango_fechas == (None, None)


# --- Exportar errores ---

def test_exportar_errores_conserva_los_valores_originales(tmp_path):
    resultado = validar(fila(ID="100"), fila(ID="34A 123", Estado="Raro"), fila(ID="101"))
    ruta = v.exportar_errores(resultado, tmp_path / "errores" / "filas_con_error.csv")
    assert ruta.read_bytes().startswith(b"\xef\xbb\xbf")
    exportado = pd.read_csv(ruta, sep=";", dtype=str, encoding="utf-8-sig")
    assert list(exportado.columns) == ["Fila", "Motivo del error", *gen.ENCABEZADOS]
    assert len(exportado) == 1
    assert exportado.iloc[0]["Fila"] == "3"
    assert exportado.iloc[0]["ID"] == "34A 123"
    assert "Estado sin mapear" in exportado.iloc[0]["Motivo del error"]
