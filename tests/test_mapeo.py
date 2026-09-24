from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest

import generador_glpi as gen
from core import historial
from core.errores import ErrorPermiso, ErrorValidacion
from core.fuentes.fuente_csv import FuenteCSV
from core.importacion import mapeo as m

ENCABEZADOS_REALES = gen.ENCABEZADOS
COLUMNAS_ESPERADAS = {
    "id_glpi": "ID",
    "titulo": "Título",
    "entidad": "Entidad",
    "estado": "Estado",
    "autor": "Autor - Autor",
    "tecnico": "Asignado a: - Técnico",
    "fecha_apertura": "Fecha de Apertura",
    "ultima_actualizacion": "Última actualización",
    "prioridad": "Prioridad",
    "ubicacion": "Ubicación",
}


@pytest.fixture
def exportacion(tmp_path):
    tickets = gen.generar_tickets(80, datetime(2026, 8, 1), datetime(2026, 9, 23), semilla=5)
    return gen.escribir_csv(gen.filas_en(tickets, datetime(2026, 9, 23, 7)), tmp_path / "glpi.csv")


def perfil_real(nombre="Exportación GLPI"):
    return m.PerfilImportacion(
        nombre=nombre, separador=";", codificacion="utf-8", formato_fecha="%d-%m-%Y %H:%M",
        mapeo=m.Mapeo(columnas=dict(COLUMNAS_ESPERADAS)),
    )


# --- Autodetección ---

def test_encabezados_reales_se_mapean_completos():
    assert m.proponer_columnas(ENCABEZADOS_REALES) == COLUMNAS_ESPERADAS


def test_normalizar():
    assert m.normalizar("Asignado a: - Técnico") == "asignadoatecnico"
    assert m.normalizar(" Última  Actualización ") == "ultimaactualizacion"


def test_variantes_de_encabezados():
    propuesta = m.proponer_columnas(
        ("id", "TITULO", "estado", "Asignado a - Tecnico", "Fecha apertura",
         "Ultima actualizacion", "PRIORIDAD", "Otra columna")
    )
    assert propuesta == {
        "id_glpi": "id", "titulo": "TITULO", "estado": "estado",
        "tecnico": "Asignado a - Tecnico", "fecha_apertura": "Fecha apertura",
        "ultima_actualizacion": "Ultima actualizacion", "prioridad": "PRIORIDAD",
    }


def test_cada_encabezado_se_usa_una_sola_vez():
    propuesta = m.proponer_columnas(("Autor", "Solicitante"))
    assert propuesta == {"autor": "Autor"}


def test_proponer_perfil_desde_el_archivo_real(exportacion):
    formato = FuenteCSV(exportacion).formato
    perfil = m.proponer_perfil(formato)
    assert perfil.mapeo.columnas == COLUMNAS_ESPERADAS
    assert (perfil.separador, perfil.codificacion, perfil.formato_fecha) == (
        ";", "utf-8", "%d-%m-%Y %H:%M",
    )
    assert perfil.separador_multivalor == "\n"
    assert m.errores_del_perfil(perfil, formato.encabezados) == []


# --- Estados y prioridades ---

def test_estados_y_prioridades_reales_precargados():
    mapeo = m.Mapeo(columnas={})
    assert mapeo.codigo_estado("Escalado") == "ESCALADO"
    assert mapeo.codigo_estado("Resueltas") == "RESUELTO"
    assert mapeo.codigo_estado("En curso (asignada)") == "EN_CURSO_ASIGNADO"
    assert mapeo.nivel_prioridad("Mayor") == 6
    assert mapeo.nivel_prioridad("Muy baja") == 1


def test_comparacion_de_valores_tolera_mayusculas_y_espacios():
    mapeo = m.Mapeo(columnas={})
    assert mapeo.codigo_estado("  en curso  (ASIGNADA) ") == "EN_CURSO_ASIGNADO"
    assert mapeo.nivel_prioridad("muy URGENTE") == 5
    assert mapeo.codigo_estado("Pendiente") is None


def test_valores_no_mapeados():
    bloque = pd.DataFrame({
        "Estado": ["Escalado", "Pendiente de revisión", "", "Cerrado"],
        "Prioridad": ["Mayor", "Crítica", "Mediana", " "],
    })
    mapeo = m.Mapeo(columnas={"estado": "Estado", "prioridad": "Prioridad"})
    assert m.valores_no_mapeados(bloque, mapeo) == ({"Pendiente de revisión"}, {"Crítica"})


def test_nuevo_estado_agregado_por_el_usuario():
    mapeo = m.Mapeo(columnas={}, estados={**m.MAPEO_ESTADOS_GLPI, "Pendiente de revisión": "EN_ESPERA"})
    assert mapeo.codigo_estado("Pendiente de revisión") == "EN_ESPERA"


# --- Validación del perfil ---

def test_falta_campo_obligatorio():
    perfil = perfil_real()
    columnas = dict(perfil.mapeo.columnas)
    del columnas["estado"]
    columnas["autor"] = ""
    errores = m.errores_del_perfil(replace(perfil, mapeo=m.Mapeo(columnas)), ENCABEZADOS_REALES)
    assert errores == ["Falta asociar el campo obligatorio «Estado»."]


def test_campos_opcionales_pueden_faltar():
    perfil = perfil_real()
    columnas = {k: v for k, v in perfil.mapeo.columnas.items()
                if k not in ("entidad", "autor", "ubicacion")}
    assert m.errores_del_perfil(replace(perfil, mapeo=m.Mapeo(columnas)), ENCABEZADOS_REALES) == []


def test_columna_inexistente_y_repetida():
    perfil = perfil_real()
    columnas = {**perfil.mapeo.columnas, "titulo": "Asunto", "autor": "Estado"}
    errores = m.errores_del_perfil(replace(perfil, mapeo=m.Mapeo(columnas)), ENCABEZADOS_REALES)
    assert "La columna «Asunto» del campo «Título» no existe en el archivo." in errores
    assert "La columna «Estado» está asociada a más de un campo." in errores


def test_codigos_de_estado_y_niveles_invalidos():
    mapeo = m.Mapeo(
        columnas=dict(COLUMNAS_ESPERADAS),
        estados={"Raro": "INVENTADO"},
        prioridades={"Crítica": 9},
    )
    errores = m.errores_del_perfil(replace(perfil_real(), mapeo=mapeo), ENCABEZADOS_REALES)
    assert any("«Raro»" in e for e in errores)
    assert any("«Crítica»" in e for e in errores)


def test_sin_nombre_ni_formato_de_fecha():
    perfil = replace(perfil_real(), nombre="  ", formato_fecha="")
    errores = m.errores_del_perfil(perfil, ENCABEZADOS_REALES)
    assert "Escriba un nombre para el perfil." in errores
    assert "Indique el formato de fecha del archivo." in errores


# --- Perfiles guardados (CA-02) ---

def test_flujo_ca02_detectar_confirmar_guardar_y_reutilizar(bd, coordinador, exportacion):
    fuente = FuenteCSV(exportacion)
    propuesto = m.proponer_perfil(fuente.formato)
    guardado = m.guardar_perfil(bd, coordinador, propuesto, fuente.formato.encabezados)
    assert guardado.id is not None

    recuperado = m.obtener_perfil(bd, guardado.id)
    assert recuperado == guardado
    assert recuperado.separador_multivalor == "\n"
    assert m.buscar_perfil_compatible(bd, fuente.formato.encabezados) == guardado
    assert historial.consultar(bd, entidad="perfil_importacion")[0]["accion"] == "CREAR"


def test_guardar_con_el_mismo_nombre_actualiza_y_registra_el_cambio(bd, coordinador):
    original = m.guardar_perfil(bd, coordinador, perfil_real(), ENCABEZADOS_REALES)
    nuevos_estados = {**m.MAPEO_ESTADOS_GLPI, "Pendiente de revisión": "EN_ESPERA"}
    cambiado = replace(original, mapeo=replace(original.mapeo, estados=nuevos_estados))
    actualizado = m.guardar_perfil(bd, coordinador, cambiado, ENCABEZADOS_REALES)
    assert actualizado.id == original.id
    assert len(m.listar_perfiles(bd)) == 1
    assert m.obtener_perfil(bd, original.id).mapeo.codigo_estado("Pendiente de revisión") == "EN_ESPERA"
    registro = historial.consultar(bd, entidad="perfil_importacion")[0]
    assert registro["accion"] == "MODIFICAR"
    assert "Pendiente de revisión" in registro["valor_nuevo"]
    assert "Pendiente de revisión" not in registro["valor_anterior"]


def test_guardar_sin_cambios_no_llena_el_historial(bd, coordinador):
    m.guardar_perfil(bd, coordinador, perfil_real(), ENCABEZADOS_REALES)
    m.guardar_perfil(bd, coordinador, perfil_real(), ENCABEZADOS_REALES)
    assert len(historial.consultar(bd, entidad="perfil_importacion")) == 1


def test_perfil_invalido_no_se_guarda(bd, coordinador):
    perfil = replace(perfil_real(), mapeo=m.Mapeo(columnas={"id_glpi": "ID"}))
    with pytest.raises(ErrorValidacion, match="Falta asociar"):
        m.guardar_perfil(bd, coordinador, perfil, ENCABEZADOS_REALES)
    assert m.listar_perfiles(bd) == []


def test_solo_el_coordinador_guarda_y_elimina_perfiles(bd, coordinador, consulta):
    with pytest.raises(ErrorPermiso):
        m.guardar_perfil(bd, consulta, perfil_real(), ENCABEZADOS_REALES)
    guardado = m.guardar_perfil(bd, coordinador, perfil_real(), ENCABEZADOS_REALES)
    with pytest.raises(ErrorPermiso):
        m.eliminar_perfil(bd, consulta, guardado.id)


def test_buscar_perfil_compatible_descarta_los_que_no_encajan(bd, coordinador):
    m.guardar_perfil(bd, coordinador, perfil_real(), ENCABEZADOS_REALES)
    otros = ("Número", "Asunto", "Estado")
    assert m.buscar_perfil_compatible(bd, otros) is None


def test_eliminar_perfil(bd, coordinador):
    guardado = m.guardar_perfil(bd, coordinador, perfil_real(), ENCABEZADOS_REALES)
    m.eliminar_perfil(bd, coordinador, guardado.id)
    assert m.listar_perfiles(bd) == []
    assert historial.consultar(bd, entidad="perfil_importacion")[0]["accion"] == "ELIMINAR"


def test_no_se_elimina_un_perfil_ya_usado(bd, coordinador):
    guardado = m.guardar_perfil(bd, coordinador, perfil_real(), ENCABEZADOS_REALES)
    with bd:
        bd.execute(
            "INSERT INTO importacion (tipo, archivo, hash, perfil_id, fecha) "
            "VALUES ('TICKETS', 'a.csv', 'h', ?, '2026-09-24 10:00:00')",
            (guardado.id,),
        )
    with pytest.raises(ErrorValidacion, match="ya se usó"):
        m.eliminar_perfil(bd, coordinador, guardado.id)
