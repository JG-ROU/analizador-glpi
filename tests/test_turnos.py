from datetime import time

import pytest

from core.errores import ErrorConfiguracion
from core.turnos import interpretar_franja, turno_para, validar_franjas


def franjas_estandar():
    return (
        interpretar_franja("Mañana", "06:00-14:00"),
        interpretar_franja("Tarde", "14:00-22:00"),
        interpretar_franja("Nocturno", "22:00-06:00"),
    )


@pytest.mark.parametrize(
    "hora, turno",
    [
        (time(0, 0), "Nocturno"),
        (time(5, 59), "Nocturno"),
        (time(6, 0), "Mañana"),
        (time(13, 59), "Mañana"),
        (time(14, 0), "Tarde"),
        (time(21, 59), "Tarde"),
        (time(22, 0), "Nocturno"),
        (time(23, 59), "Nocturno"),
    ],
)
def test_turno_para_limites_de_franja(hora, turno):
    franjas = franjas_estandar()
    validar_franjas(franjas)
    assert turno_para(hora, franjas) == turno


def test_franja_acepta_hora_de_un_digito_y_espacios():
    franja = interpretar_franja("Mañana", " 6:00 - 14:00 ")
    assert (franja.inicio, franja.fin) == (360, 840)


@pytest.mark.parametrize("texto", ["06:00", "6-14", "25:00-06:00", "06:60-07:00", "abc"])
def test_franja_con_formato_invalido(texto):
    with pytest.raises(ErrorConfiguracion, match="Mañana"):
        interpretar_franja("Mañana", texto)


def test_franja_que_empieza_y_termina_igual():
    with pytest.raises(ErrorConfiguracion, match="misma hora"):
        interpretar_franja("Mañana", "06:00-06:00")


def test_franjas_solapadas_se_rechazan():
    franjas = franjas_estandar() + (interpretar_franja("Día Intermedio", "10:00-18:00"),)
    with pytest.raises(ErrorConfiguracion, match="se solapan a las 10:00"):
        validar_franjas(franjas)


def test_franjas_con_hueco_se_rechazan():
    franjas = (
        interpretar_franja("Mañana", "06:00-14:00"),
        interpretar_franja("Tarde", "14:00-22:00"),
        interpretar_franja("Nocturno", "22:30-06:00"),
    )
    with pytest.raises(ErrorConfiguracion, match="cubre las 22:00"):
        validar_franjas(franjas)


def test_sin_franjas_se_rechaza():
    with pytest.raises(ErrorConfiguracion):
        validar_franjas(())
