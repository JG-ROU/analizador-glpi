"""Lista de tickets de Novedades (PAN-04) y detalle de un ticket (PAN-05).

Un usuario de consulta solo ve los tickets donde es técnico asignado; la jefatura
sin técnico no ve tickets individuales (RNF-07).
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from core import parametros, reloj, seguridad
from core.analisis.filtros import Filtros
from core.analisis.kpis import NOMBRE_PRIORIDAD
from core.analisis.periodos import Periodo
from core.analisis.series import NOMBRE_ESTADO
from core.dominio import NOMBRE_TIPO_CASO, PRIORIDADES
from core.errores import ErrorPermiso, ErrorValidacion
from core.importacion import eventos as ev
from core.seguridad import Sesion

TODOS = "TODOS"
SIN_ACTUALIZAR = "SIN_ACTUALIZAR"
SIN_CERRAR = "SIN_CERRAR"
P1_ABIERTOS = "P1_ABIERTOS"
ESCALADOS_ANTIGUOS = "ESCALADOS_ANTIGUOS"

ACCESOS_RAPIDOS = {
    TODOS: "Abiertos y recibidos en el período",
    SIN_ACTUALIZAR: "Sin actualizar más del plazo",
    SIN_CERRAR: "Resueltos sin cerrar",
    P1_ABIERTOS: "P1 abiertos",
    ESCALADOS_ANTIGUOS: "Escalados antiguos",
}
COLUMNAS = (
    "ID", "Título", "Estado", "Prioridad", "Técnico", "Apertura", "Última actualización",
    "Horas sin actualizar", "Turno", "Tipo de caso", "Autor", "Entidad", "Ubicación",
)
ABIERTOS = "t.estado_codigo NOT IN ('RESUELTO', 'CERRADO')"


@dataclass
class DetalleTicket:
    ticket: dict
    tecnicos: list[str]
    cambios: list[dict]
    eventos: list[dict]


def restriccion_tickets(conexion: sqlite3.Connection, sesion: Sesion) -> tuple[str, list]:
    """Condición SQL que limita los tickets visibles por la sesión."""
    if sesion.es_coordinador:
        return "", []
    if sesion.tecnico_id is None:
        raise ErrorPermiso(
            "Su usuario no tiene un técnico asociado: puede ver los indicadores del equipo, "
            "pero no la lista de tickets."
        )
    return (
        " AND t.id_glpi IN (SELECT ticket_id FROM ticket_tecnico WHERE tecnico_id = ?)",
        [sesion.tecnico_id],
    )


def listar(
    conexion: sqlite3.Connection,
    sesion: Sesion,
    periodo: Periodo,
    acceso: str = TODOS,
    filtros: Filtros = Filtros(),
    ahora: datetime | None = None,
) -> pd.DataFrame:
    """Tickets para la tabla de Novedades, más recientes primero."""
    if acceso not in ACCESOS_RAPIDOS:
        raise ErrorValidacion("Acceso rápido desconocido.")
    ahora = ahora or reloj.ahora()
    if filtros.tecnico_id is not None:
        seguridad.tecnico_permitido(sesion, filtros.tecnico_id)
    restriccion, valores_restriccion = restriccion_tickets(conexion, sesion)
    condicion, valores = filtros.sql("t")
    if acceso == TODOS:
        where = f"({ABIERTOS} OR (t.fecha_apertura >= ? AND t.fecha_apertura < ?))"
        valores_acceso = [periodo.inicio.isoformat(sep=" "), periodo.fin.isoformat(sep=" ")]
    elif acceso == SIN_CERRAR:
        limite = ahora - timedelta(days=parametros.entero(conexion, "dias_resuelto_sin_cerrar"))
        where = "t.estado_codigo = 'RESUELTO' AND t.fecha_solucion < ?"
        valores_acceso = [limite.isoformat(sep=" ")]
    elif acceso == P1_ABIERTOS:
        where = f"{ABIERTOS} AND t.es_p1 = 1"
        valores_acceso = []
    elif acceso == ESCALADOS_ANTIGUOS:
        limite = ahora - timedelta(days=parametros.entero(conexion, "dias_escalado_alerta"))
        where = (
            "t.estado_codigo = 'ESCALADO' AND (SELECT MAX(e.fecha_evento) FROM ticket_evento e "
            f"WHERE e.ticket_id = t.id_glpi AND e.tipo = '{ev.ESCALAMIENTO}') < ?"
        )
        valores_acceso = [limite.isoformat(sep=" ")]
    else:  # SIN_ACTUALIZAR: se filtra abajo con el umbral de cada prioridad
        where = ABIERTOS
        valores_acceso = []
    filas = conexion.execute(
        "SELECT t.*, k.nombre_mostrar AS tecnico FROM ticket t "
        "LEFT JOIN tecnico k ON k.id = t.tecnico_principal_id "
        f"WHERE {where}{condicion}{restriccion} ORDER BY t.ultima_actualizacion DESC",
        [*valores_acceso, *valores, *valores_restriccion],
    ).fetchall()
    if acceso == SIN_ACTUALIZAR:
        umbrales = {
            p.nivel: parametros.decimal_opcional(conexion, f"horas_sin_actualizar_{p.clave}") for p in PRIORIDADES
        }
        filas = [
            f for f in filas
            if umbrales.get(f["prioridad_nivel"]) is not None
            and _horas_desde(f["ultima_actualizacion"], ahora) > umbrales[f["prioridad_nivel"]]
        ]
    return pd.DataFrame(
        [
            {
                "ID": f["id_glpi"],
                "Título": f["titulo"],
                "Estado": NOMBRE_ESTADO[f["estado_codigo"]],
                "Prioridad": NOMBRE_PRIORIDAD[f["prioridad_nivel"]],
                "Técnico": f["tecnico"] or "Sin asignar",
                "Apertura": f["fecha_apertura"][:16],
                "Última actualización": f["ultima_actualizacion"][:16],
                "Horas sin actualizar": _horas_desde(f["ultima_actualizacion"], ahora)
                if f["estado_codigo"] not in ("RESUELTO", "CERRADO") else None,
                "Turno": f["turno_apertura"],
                "Tipo de caso": NOMBRE_TIPO_CASO[f["tipo_caso"]],
                "Autor": f["autor"],
                "Entidad": f["entidad"],
                "Ubicación": f["ubicacion"],
            }
            for f in filas
        ],
        columns=list(COLUMNAS),
    )


def _horas_desde(texto: str, ahora: datetime) -> float:
    return round(max(0.0, (ahora - datetime.fromisoformat(texto)).total_seconds() / 3600), 1)


def detalle(conexion: sqlite3.Connection, sesion: Sesion, id_glpi: int) -> DetalleTicket:
    restriccion, valores = restriccion_tickets(conexion, sesion)
    fila = conexion.execute(
        "SELECT t.*, k.nombre_mostrar AS tecnico FROM ticket t "
        "LEFT JOIN tecnico k ON k.id = t.tecnico_principal_id "
        f"WHERE t.id_glpi = ?{restriccion}",
        [id_glpi, *valores],
    ).fetchone()
    if fila is None:
        raise ErrorValidacion(f"El ticket {id_glpi} no existe o no tiene permiso para verlo.")
    tecnicos = [
        f[0] for f in conexion.execute(
            "SELECT k.nombre_mostrar FROM ticket_tecnico tt JOIN tecnico k ON k.id = tt.tecnico_id "
            "WHERE tt.ticket_id = ? ORDER BY tt.orden", (id_glpi,)
        )
    ]
    cambios = [
        dict(f) for f in conexion.execute(
            "SELECT c.detectado_en, c.campo, c.valor_anterior, c.valor_nuevo, i.archivo "
            "FROM ticket_cambio c JOIN importacion i ON i.id = c.importacion_id "
            "WHERE c.ticket_id = ? ORDER BY c.id", (id_glpi,)
        )
    ]
    eventos = [
        dict(f) for f in conexion.execute(
            "SELECT e.fecha_evento, e.tipo, e.origen, k.nombre_mostrar AS tecnico FROM ticket_evento e "
            "LEFT JOIN tecnico k ON k.id = e.tecnico_id WHERE e.ticket_id = ? ORDER BY e.fecha_evento, e.id",
            (id_glpi,),
        )
    ]
    return DetalleTicket(dict(fila), tecnicos, cambios, eventos)
