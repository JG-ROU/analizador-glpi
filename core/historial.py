"""Historial de cambios manuales, de solo inserción (RNF-09, PAN-14).

`registrar` no confirma la transacción: se llama dentro de la misma transacción
del cambio, para que el cambio y su registro se guarden juntos o ninguno.
"""

import sqlite3
from typing import Any

from core import reloj


def _texto(valor: Any) -> str | None:
    return None if valor is None else str(valor)


def registrar(
    conexion: sqlite3.Connection,
    *,
    entidad: str,
    entidad_id: Any,
    accion: str,
    usuario_id: int | None,
    campo: str | None = None,
    valor_anterior: Any = None,
    valor_nuevo: Any = None,
    nota: str | None = None,
) -> None:
    conexion.execute(
        "INSERT INTO historial (entidad, entidad_id, accion, campo, valor_anterior, "
        "valor_nuevo, nota, usuario_id, fecha_hora) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entidad,
            _texto(entidad_id),
            accion,
            campo,
            _texto(valor_anterior),
            _texto(valor_nuevo),
            nota,
            usuario_id,
            reloj.ahora().isoformat(sep=" "),
        ),
    )


def consultar(
    conexion: sqlite3.Connection,
    entidad: str | None = None,
    entidad_id: Any = None,
    limite: int = 1000,
) -> list[sqlite3.Row]:
    """Registros más recientes primero, con el nombre del usuario que hizo el cambio."""
    condiciones, valores = [], []
    if entidad is not None:
        condiciones.append("h.entidad = ?")
        valores.append(entidad)
    if entidad_id is not None:
        condiciones.append("h.entidad_id = ?")
        valores.append(_texto(entidad_id))
    donde = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    return conexion.execute(
        "SELECT h.*, u.nombre AS usuario FROM historial h "
        f"LEFT JOIN usuario u ON u.id = h.usuario_id {donde} "
        "ORDER BY h.id DESC LIMIT ?",
        (*valores, limite),
    ).fetchall()
