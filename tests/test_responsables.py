"""Métricas por técnico (PAN-07, REP-03) y permisos de consulta (CA-08)."""

from datetime import datetime

import pytest

from core import seguridad
from core.analisis import periodos, responsables
from core.errores import ErrorPermiso
from test_kpis import AHORA, SEPTIEMBRE, escenario, tecnico_id
from ayudas import importar_diario


def d(mes, dia):
    return datetime(2026, mes, dia, 10, 0)


@pytest.fixture
def datos(bd, coordinador, tmp_path):
    importar_diario(bd, coordinador, escenario(), d(8, 25), datetime(2026, 10, 3, 23, 0), tmp_path)
    with bd:
        bd.execute("UPDATE parametro SET valor = '72' WHERE clave = 'sla_horas_urgente'")
        bd.execute("UPDATE parametro SET valor = '96' WHERE clave = 'sla_horas_mediana'")
        bd.execute("UPDATE tecnico SET turno = 'Día Intermedio' WHERE nombre_glpi = 'Tecnico 03'")
    return bd


def sesion_de(bd, coordinador, tecnico):
    usuario = seguridad.crear_usuario(
        bd, coordinador, nombre=f"Usuario {tecnico}", perfil=seguridad.CONSULTA, pin="5555",
        tecnico_id=tecnico_id(bd, tecnico),
    )
    return seguridad.iniciar_sesion(bd, usuario, "5555")


def por_nombre(lista):
    return {m.nombre: m for m in lista}


def test_coordinador_ve_a_todos_los_tecnicos(datos, coordinador):
    lista = por_nombre(responsables.metricas(datos, coordinador, SEPTIEMBRE, ahora=AHORA))
    assert set(lista) == {"Tecnico 01", "Tecnico 02", "Tecnico 03", "Tecnico 04"}

    t1 = lista["Tecnico 01"]  # T1: 2 escalamientos y 1 solución en septiembre
    assert (t1.atendidos, t1.soluciones, t1.escalamientos) == (1, 1, 2)
    assert t1.mediana_resolucion == 192.0 and t1.sla == 0.0

    t2 = lista["Tecnico 02"]  # A1 y A2 resueltos en 48 h; A1 sigue sin cerrar
    assert (t2.atendidos, t2.mediana_resolucion, t2.sla) == (2, 48.0, 100.0)
    assert (t2.sin_cerrar_cantidad, t2.sin_cerrar) == (1, 50.0)

    t3 = lista["Tecnico 03"]
    assert t3.turno == "Día Intermedio"
    assert (t3.abiertos, t3.abiertos_por_prioridad) == (1, {"Mediana": 1})  # A3 al 1-oct

    t4 = lista["Tecnico 04"]
    assert (t4.abiertos, t4.sin_actualizar, t4.atendidos) == (6, 6, 0)
    assert t4.muestra_pequena


def test_reaperturas_por_tecnico(bd, coordinador, tmp_path):
    from ayudas import ticket
    import generador_glpi as gen

    reabierto = ticket(
        50, d(9, 1), "Tecnico 05", "Baja",
        (d(9, 2), gen.RESUELTO), (d(9, 3), gen.ASIGNADO), (d(9, 4), gen.RESUELTO),
    )
    importar_diario(bd, coordinador, [reabierto], d(9, 1), datetime(2026, 9, 5, 23, 0), tmp_path)
    lista = por_nombre(responsables.metricas(bd, coordinador, SEPTIEMBRE, ahora=AHORA))
    assert lista["Tecnico 05"].reaperturas == 1


def test_consulta_solo_ve_sus_metricas(datos, coordinador):
    sesion = sesion_de(datos, coordinador, "Tecnico 02")
    lista = responsables.metricas(datos, sesion, SEPTIEMBRE, ahora=AHORA)
    assert [m.nombre for m in lista] == ["Tecnico 02"]
    with pytest.raises(ErrorPermiso):
        responsables.metricas(datos, sesion, SEPTIEMBRE, tecnico_id(datos, "Tecnico 01"), ahora=AHORA)


def test_jefatura_sin_tecnico_no_ve_metricas_individuales(datos, consulta):
    with pytest.raises(ErrorPermiso):
        responsables.metricas(datos, consulta, SEPTIEMBRE, ahora=AHORA)


def test_tecnico_inactivo_no_aparece_en_la_lista(datos, coordinador):
    with datos:
        datos.execute("UPDATE tecnico SET activo = 0 WHERE nombre_glpi = 'Tecnico 04'")
    nombres = {m.nombre for m in responsables.metricas(datos, coordinador, SEPTIEMBRE, ahora=AHORA)}
    assert "Tecnico 04" not in nombres


def test_atendidos_por_semana(datos, coordinador):
    serie = responsables.atendidos_por_semana(
        datos, coordinador, tecnico_id(datos, "Tecnico 02"), SEPTIEMBRE, ahora=AHORA
    )
    assert [(s.codigo, n) for s, n in serie] == [
        ("2026-W36", 2), ("2026-W37", 0), ("2026-W38", 0), ("2026-W39", 0), ("2026-W40", 0),
    ]


def test_atendidos_por_semana_de_otro_tecnico_prohibido(datos, coordinador):
    sesion = sesion_de(datos, coordinador, "Tecnico 02")
    with pytest.raises(ErrorPermiso):
        responsables.atendidos_por_semana(
            datos, sesion, tecnico_id(datos, "Tecnico 01"), periodos.mes(2026, 9), ahora=AHORA
        )
