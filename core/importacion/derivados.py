"""Campos derivados del ticket (IMP-04, CA-05). Funciones puras, sin BD.

Los derivados que dependen de los eventos detectados entre importaciones
(fecha_solucion, fecha_cierre y si tuvo escalamientos) se calculan en la carga
(T10) y usan `horas_entre` e `inferir_tipo_caso` de este módulo.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.dominio import (
    CRITICO_P1,
    ESCALADO,
    ESCALAMIENTO,
    ESTADOS_SOLUCIONADOS,
    GESTION,
    RESUELTO,
)
from core.turnos import Franja, turno_para

DECIMALES_HORAS = 2


@dataclass(frozen=True)
class Derivados:
    es_p1: bool
    escalado: bool
    turno_apertura: str
    tecnico_principal: str | None
    tecnicos_adicionales: tuple[str, ...]
    hash_fila: str


def es_p1(prioridad_nivel: int, prioridad_p1: int) -> bool:
    """P1 si el nivel alcanza el parámetro `prioridad_p1` (por defecto 6 = Mayor)."""
    return prioridad_nivel >= prioridad_p1


def esta_abierto(estado_codigo: str) -> bool:
    return estado_codigo not in ESTADOS_SOLUCIONADOS


def esta_escalado(estado_codigo: str) -> bool:
    return estado_codigo == ESCALADO


def turno_apertura(fecha_apertura: datetime, franjas: Sequence[Franja]) -> str:
    return turno_para(fecha_apertura.time(), franjas)


def horas_entre(inicio: datetime | None, fin: datetime | None) -> float | None:
    """Horas de inicio a fin. None si falta una fecha o si el fin es anterior al inicio."""
    if inicio is None or fin is None or fin < inicio:
        return None
    return round((fin - inicio).total_seconds() / 3600, DECIMALES_HORAS)


def inferir_tipo_caso(es_p1: bool, tuvo_escalamiento: bool) -> str:
    """Crítico P1 si es P1; Escalamiento si alguna vez se escaló; si no, Gestión."""
    if es_p1:
        return CRITICO_P1
    if tuvo_escalamiento:
        return ESCALAMIENTO
    return GESTION


def resuelto_sin_cerrar(
    estado_codigo: str, fecha_solucion: datetime | None, corte: datetime, dias: int
) -> bool:
    """En Resuelto desde hace más de `dias` días a la fecha de corte (se calcula al consultar)."""
    if estado_codigo != RESUELTO or fecha_solucion is None:
        return False
    return corte - fecha_solucion > timedelta(days=dias)


def hash_fila(fila: dict) -> str:
    """Huella de los valores del ticket; si no cambia, la carga puede saltarse la fila."""
    partes = [
        str(fila.get(campo) or "")
        for campo in (
            "titulo", "entidad", "estado", "autor", "fecha_apertura",
            "ultima_actualizacion", "prioridad", "ubicacion",
        )
    ]
    partes.append("\n".join(fila.get("tecnicos") or ()))
    return hashlib.sha256("\x1f".join(partes).encode("utf-8")).hexdigest()


def derivar(fila: dict, franjas: Sequence[Franja], prioridad_p1: int) -> Derivados:
    """Derivados de una fila ya validada (ver validacion.ValidadorTickets)."""
    tecnicos = tuple(fila["tecnicos"] or ())
    return Derivados(
        es_p1=es_p1(fila["prioridad_nivel"], prioridad_p1),
        escalado=esta_escalado(fila["estado_codigo"]),
        turno_apertura=turno_apertura(fila["fecha_apertura"], franjas),
        tecnico_principal=tecnicos[0] if tecnicos else None,
        tecnicos_adicionales=tecnicos[1:],
        hash_fila=hash_fila(fila),
    )
