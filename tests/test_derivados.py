"""Casos de prueba de IMP-04 (CA-05)."""

from datetime import datetime

import pandas as pd
import pytest

import generador_glpi as gen
from core.fuentes.base import COLUMNA_FILA
from core.importacion import derivados as d
from core.importacion import mapeo as m
from core.importacion import validacion as v
from core.turnos import interpretar_franja

FRANJAS = (
    interpretar_franja("Mañana", "06:00-14:00"),
    interpretar_franja("Tarde", "14:00-22:00"),
    interpretar_franja("Nocturno", "22:00-06:00"),
)
P1_POR_DEFECTO = 6


def fila_validada(**valores):
    """Fila del CSV real pasada por la validación (T08), como la recibe la carga."""
    crudo = {
        "ID": "346 649", "Título": "Novedad", "Entidad": "Grupo > Empresa",
        "Estado": "En curso (asignada)", "Autor - Autor": "Autor 1",
        "Asignado a: - Técnico": "Tecnico 1", "Fecha de Apertura": "06-04-2026 05:21",
        "Última actualización": "22-09-2026 14:22", "Prioridad": "Mediana",
        "Ubicación": "Departamento > Filial > Cliente > Estación",
    }
    crudo.update(valores)
    bloque = pd.DataFrame([crudo], columns=list(gen.ENCABEZADOS))
    bloque.insert(0, COLUMNA_FILA, [2])
    perfil = m.PerfilImportacion(
        nombre="Prueba", separador=";", codificacion="utf-8", formato_fecha="%d-%m-%Y %H:%M",
        mapeo=m.Mapeo(columnas=m.proponer_columnas(gen.ENCABEZADOS)),
    )
    fila = v.validar([bloque], perfil).filas.iloc[0].to_dict()
    assert fila["resultado"] != v.ERROR, fila["motivos"]
    fila["fecha_apertura"] = fila["fecha_apertura"].to_pydatetime()
    return fila


# --- CA-05: derivación completa de la fila real ---

def test_ca05_fila_real():
    fila = fila_validada()
    derivados = d.derivar(fila, FRANJAS, P1_POR_DEFECTO)
    assert fila["id_glpi"] == 346649
    assert fila["estado_codigo"] == "EN_CURSO_ASIGNADO"
    assert fila["prioridad_nivel"] == 3
    assert derivados.es_p1 is False
    assert derivados.tecnico_principal == "Tecnico 1"
    assert derivados.tecnicos_adicionales == ()
    assert derivados.turno_apertura == "Nocturno"  # 05:21
    assert derivados.escalado is False


def test_ca05_varios_tecnicos():
    fila = fila_validada(**{"Asignado a: - Técnico": "Tecnico 2\n\nTecnico 5\nTecnico 7"})
    derivados = d.derivar(fila, FRANJAS, P1_POR_DEFECTO)
    assert derivados.tecnico_principal == "Tecnico 2"
    assert derivados.tecnicos_adicionales == ("Tecnico 5", "Tecnico 7")


def test_ca05_sin_tecnico():
    derivados = d.derivar(fila_validada(**{"Asignado a: - Técnico": ""}), FRANJAS, P1_POR_DEFECTO)
    assert derivados.tecnico_principal is None and derivados.tecnicos_adicionales == ()


@pytest.mark.parametrize(
    "prioridad, parametro, esperado",
    [("Mayor", 6, True), ("Muy urgente", 6, False), ("Muy urgente", 5, True),
     ("Urgente", 5, False), ("Muy baja", 6, False)],
)
def test_ca05_es_p1_segun_parametro(prioridad, parametro, esperado):
    fila = fila_validada(Prioridad=prioridad)
    assert d.derivar(fila, FRANJAS, parametro).es_p1 is esperado


def test_ca05_escalado_segun_estado_actual():
    assert d.derivar(fila_validada(Estado="Escalado"), FRANJAS, P1_POR_DEFECTO).escalado
    assert not d.derivar(fila_validada(Estado="En espera"), FRANJAS, P1_POR_DEFECTO).escalado


@pytest.mark.parametrize(
    "hora, turno",
    [("05:59", "Nocturno"), ("06:00", "Mañana"), ("13:59", "Mañana"), ("14:00", "Tarde"),
     ("21:59", "Tarde"), ("22:00", "Nocturno"), ("00:00", "Nocturno")],
)
def test_ca05_turno_apertura(hora, turno):
    fila = fila_validada(**{"Fecha de Apertura": f"10-09-2026 {hora}"})
    assert d.derivar(fila, FRANJAS, P1_POR_DEFECTO).turno_apertura == turno


# --- Horas ---

def test_ca05_horas_resolucion():
    apertura = datetime(2026, 9, 1, 8, 0)
    assert d.horas_entre(apertura, datetime(2026, 9, 2, 10, 30)) == 26.5
    assert d.horas_entre(apertura, datetime(2026, 9, 1, 8, 20)) == 0.33
    assert d.horas_entre(apertura, apertura) == 0


def test_horas_sin_fecha_o_negativas():
    apertura = datetime(2026, 9, 1, 8, 0)
    assert d.horas_entre(apertura, None) is None
    assert d.horas_entre(None, apertura) is None
    assert d.horas_entre(apertura, datetime(2026, 8, 31)) is None


# --- Tipo de caso y estados ---

@pytest.mark.parametrize(
    "p1, escalamiento, tipo",
    [(True, True, "CRITICO_P1"), (True, False, "CRITICO_P1"),
     (False, True, "ESCALAMIENTO"), (False, False, "GESTION")],
)
def test_inferir_tipo_caso(p1, escalamiento, tipo):
    assert d.inferir_tipo_caso(p1, escalamiento) == tipo


def test_esta_abierto():
    assert d.esta_abierto("ESCALADO") and d.esta_abierto("NUEVO") and d.esta_abierto("EN_ESPERA")
    assert not d.esta_abierto("RESUELTO") and not d.esta_abierto("CERRADO")


def test_resuelto_sin_cerrar():
    solucion = datetime(2026, 9, 20, 10, 0)
    assert d.resuelto_sin_cerrar("RESUELTO", solucion, datetime(2026, 9, 22, 10, 1), 2)
    assert not d.resuelto_sin_cerrar("RESUELTO", solucion, datetime(2026, 9, 22, 10, 0), 2)
    assert not d.resuelto_sin_cerrar("CERRADO", solucion, datetime(2026, 9, 30), 2)
    assert not d.resuelto_sin_cerrar("RESUELTO", None, datetime(2026, 9, 30), 2)


# --- Huella de la fila ---

def test_hash_cambia_solo_si_cambia_el_ticket():
    base = fila_validada()
    igual = fila_validada()
    igual["_fila"] = 99
    assert d.hash_fila(base) == d.hash_fila(igual)
    for cambios in (
        {"Estado": "Escalado"},
        {"Última actualización": "23-09-2026 08:00"},
        {"Asignado a: - Técnico": "Tecnico 1\nTecnico 2"},
        {"Prioridad": "Urgente"},
    ):
        assert d.hash_fila(fila_validada(**cambios)) != d.hash_fila(base), cambios
