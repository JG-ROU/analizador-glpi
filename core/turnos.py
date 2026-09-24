"""Franjas de turno para derivar el turno de apertura del ticket (IMP-04).

Las franjas de apertura no pueden solaparse y deben cubrir las 24 horas.
Una franja cuyo fin es menor que su inicio cruza la medianoche (22:00-06:00).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time

from core.errores import ErrorConfiguracion

MINUTOS_DIA = 24 * 60

_PATRON_FRANJA = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


@dataclass(frozen=True)
class Franja:
    turno: str
    inicio: int  # minuto del día, incluido
    fin: int  # minuto del día, excluido

    def contiene(self, minuto: int) -> bool:
        if self.inicio < self.fin:
            return self.inicio <= minuto < self.fin
        return minuto >= self.inicio or minuto < self.fin

    @property
    def texto(self) -> str:
        """«HH:MM-HH:MM», como en config.ini."""
        return f"{_hhmm(self.inicio)}-{_hhmm(self.fin)}"


def _hhmm(minuto: int) -> str:
    return f"{minuto // 60:02d}:{minuto % 60:02d}"


def interpretar_franja(turno: str, texto: str) -> Franja:
    """Convierte «HH:MM-HH:MM» en una Franja."""
    coincidencia = _PATRON_FRANJA.match(texto)
    if not coincidencia:
        raise ErrorConfiguracion(
            f"La franja del turno «{turno}» no es válida: «{texto}». "
            "Use el formato HH:MM-HH:MM, por ejemplo 06:00-14:00."
        )
    h1, m1, h2, m2 = (int(parte) for parte in coincidencia.groups())
    if not (0 <= h1 <= 23 and 0 <= h2 <= 23 and 0 <= m1 <= 59 and 0 <= m2 <= 59):
        raise ErrorConfiguracion(
            f"La franja del turno «{turno}» tiene una hora inválida: «{texto}»."
        )
    inicio, fin = h1 * 60 + m1, h2 * 60 + m2
    if inicio == fin:
        raise ErrorConfiguracion(
            f"La franja del turno «{turno}» empieza y termina a la misma hora."
        )
    return Franja(turno, inicio, fin)


def validar_franjas(franjas: Sequence[Franja]) -> None:
    """Exige franjas sin solapes que cubran las 24 horas."""
    if not franjas:
        raise ErrorConfiguracion("No hay franjas de turno en la sección [turnos].")
    duenos: list[str | None] = [None] * MINUTOS_DIA
    for franja in franjas:
        for minuto in range(MINUTOS_DIA):
            if not franja.contiene(minuto):
                continue
            if duenos[minuto] is not None:
                raise ErrorConfiguracion(
                    f"Las franjas de «{duenos[minuto]}» y «{franja.turno}» se solapan "
                    f"a las {_hhmm(minuto)}. Las franjas de apertura no pueden solaparse."
                )
            duenos[minuto] = franja.turno
    if None in duenos:
        minuto = duenos.index(None)
        raise ErrorConfiguracion(
            f"Ninguna franja de turno cubre las {_hhmm(minuto)}. "
            "Las franjas deben cubrir las 24 horas."
        )


def turno_para(hora: time, franjas: Sequence[Franja]) -> str:
    """Turno al que pertenece una hora, según franjas ya validadas."""
    minuto = hora.hour * 60 + hora.minute
    for franja in franjas:
        if franja.contiene(minuto):
            return franja.turno
    raise ValueError(f"Ninguna franja cubre las {_hhmm(minuto)}")
