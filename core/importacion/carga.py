"""Carga incremental de tickets validados (IMP-03, IMP-05, IMP-06, CA-04).

Todo el archivo se guarda en una sola transacción: si algo falla, no queda nada
a medias. Antes de cargar se respalda la BD. Por cada ticket:
- nuevo: se inserta con los eventos que explican su estado actual (PRIMERA_VEZ);
- existente sin cambios (misma huella): solo se marca la importación;
- existente con una última actualización más antigua que la guardada: se ignora,
  para que un archivo viejo no haga retroceder los datos;
- existente con cambios: se registran los cambios de estado, técnico y prioridad
  en `ticket_cambio` y los eventos en `ticket_evento`, y se actualiza.
"""

import logging
import sqlite3
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from core import historial, parametros, reloj, seguridad
from core.db import respaldo
from core.errores import ErrorAplicacion, ErrorValidacion
from core.importacion import derivados, eventos as ev
from core.importacion.mapeo import PerfilImportacion
from core.importacion.validacion import ADVERTENCIA, ERROR, VALIDA, ResultadoValidacion
from core.seguridad import Sesion
from core.turnos import Franja

log = logging.getLogger(__name__)

TIPO_TICKETS = "TICKETS"
ORIGEN_MANUAL = "MANUAL"
AVISAR_CADA = 500

Progreso = Callable[[int, int], None]


@dataclass
class ResumenImportacion:
    importacion_id: int
    archivo: str
    filas_leidas: int
    filas_validas: int
    filas_advertencia: int
    filas_error: int
    nuevos: int = 0
    actualizados: int = 0
    sin_cambios: int = 0
    omitidos_por_antiguos: int = 0
    cambios: int = 0
    eventos: Counter = field(default_factory=Counter)
    respaldo: Path | None = None
    hallazgos: object | None = None  # ResumenDeteccion, si se ejecutaron los hallazgos después
    snapshots: list[str] = field(default_factory=list)  # períodos cuyo snapshot se generó después
    notificaciones: list = field(default_factory=list)  # NOT-02 y NOT-05 después de importar


def _iso(fecha: datetime | None) -> str | None:
    return None if fecha is None else fecha.isoformat(sep=" ")


def _fecha(texto: str | None) -> datetime | None:
    return None if texto is None else datetime.fromisoformat(texto)


def importacion_previa(conexion: sqlite3.Connection, hash_archivo: str) -> sqlite3.Row | None:
    """La importación anterior del mismo archivo (mismo hash), si existe."""
    return conexion.execute(
        "SELECT i.id, i.archivo, i.fecha, u.nombre AS usuario FROM importacion i "
        "LEFT JOIN usuario u ON u.id = i.usuario_id WHERE i.tipo = ? AND i.hash = ?",
        (TIPO_TICKETS, hash_archivo),
    ).fetchone()


def ultima_importacion(conexion: sqlite3.Connection) -> datetime | None:
    """Fecha de la última importación de tickets, para la barra superior y NOT-01."""
    fila = conexion.execute(
        "SELECT MAX(fecha) FROM importacion WHERE tipo = ?", (TIPO_TICKETS,)
    ).fetchone()
    return _fecha(fila[0])


def historial_importaciones(conexion: sqlite3.Connection, limite: int = 200) -> pd.DataFrame:
    filas = conexion.execute(
        "SELECT i.fecha, i.tipo, i.archivo, u.nombre AS usuario, p.nombre AS perfil, i.filas_leidas, "
        "i.filas_validas, i.filas_advertencia, i.filas_error, i.fecha_min, i.fecha_max "
        "FROM importacion i LEFT JOIN usuario u ON u.id = i.usuario_id "
        "LEFT JOIN perfil_importacion p ON p.id = i.perfil_id ORDER BY i.id DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return pd.DataFrame(
        [
            {
                "Fecha": f["fecha"][:16], "Tipo": "Tickets" if f["tipo"] == TIPO_TICKETS else "Seguimientos",
                "Archivo": f["archivo"], "Usuario": f["usuario"],
                "Perfil": f["perfil"], "Leídas": f["filas_leidas"], "Válidas": f["filas_validas"],
                "Con advertencia": f["filas_advertencia"], "Con error": f["filas_error"],
                "Apertura desde": (f["fecha_min"] or "")[:10], "Apertura hasta": (f["fecha_max"] or "")[:10],
            }
            for f in filas
        ],
        columns=["Fecha", "Tipo", "Archivo", "Usuario", "Perfil", "Leídas", "Válidas", "Con advertencia",
                 "Con error", "Apertura desde", "Apertura hasta"],
    )


def importar(
    conexion: sqlite3.Connection,
    sesion: Sesion,
    *,
    archivo: str,
    hash_archivo: str,
    perfil: PerfilImportacion,
    validacion: ResultadoValidacion,
    franjas: Sequence[Franja],
    carpeta_respaldos: Path,
    retencion_respaldos: int,
    progreso: Progreso | None = None,
) -> ResumenImportacion:
    """Guarda las filas válidas y con advertencia de un archivo ya validado."""
    seguridad.exigir_coordinador(sesion)
    previa = importacion_previa(conexion, hash_archivo)
    if previa is not None:
        raise ErrorValidacion(
            f"Este archivo ya se importó el {previa['fecha'][:16]} "
            f"(«{previa['archivo']}»). No se volvió a cargar."
        )
    ruta_respaldo = respaldo.respaldar_antes_de_importar(
        conexion, carpeta_respaldos, retencion_respaldos
    )
    cargador = _Cargador(conexion, franjas, parametros.entero(conexion, "prioridad_p1"))
    fecha_min, fecha_max = validacion.rango_fechas
    ahora = reloj.ahora()
    try:
        with conexion:
            cursor = conexion.execute(
                "INSERT INTO importacion (tipo, archivo, hash, perfil_id, usuario_id, fecha, "
                "filas_leidas, filas_validas, filas_advertencia, filas_error, fecha_min, fecha_max) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    TIPO_TICKETS, archivo, hash_archivo, perfil.id, sesion.usuario_id,
                    _iso(ahora), validacion.filas_leidas, validacion.conteo(VALIDA),
                    validacion.conteo(ADVERTENCIA), validacion.conteo(ERROR),
                    _iso(fecha_min), _iso(fecha_max),
                ),
            )
            resumen = ResumenImportacion(
                importacion_id=cursor.lastrowid,
                archivo=archivo,
                filas_leidas=validacion.filas_leidas,
                filas_validas=validacion.conteo(VALIDA),
                filas_advertencia=validacion.conteo(ADVERTENCIA),
                filas_error=validacion.conteo(ERROR),
                respaldo=ruta_respaldo,
            )
            cargador.cargar(validacion.cargables, resumen, ahora, progreso)
            historial.registrar(
                conexion, entidad="importacion", entidad_id=resumen.importacion_id,
                accion="IMPORTAR", usuario_id=sesion.usuario_id, valor_nuevo=archivo,
                nota=(
                    f"{resumen.nuevos} nuevos, {resumen.actualizados} actualizados, "
                    f"{resumen.sin_cambios} sin cambios, {resumen.filas_error} filas con error"
                ),
            )
    except sqlite3.Error as error:
        raise ErrorAplicacion(
            "La importación no se completó y no se guardó ningún dato. "
            f"La base de datos quedó como estaba (respaldo: {ruta_respaldo.name}).",
            detalle=repr(error),
        ) from error
    log.info(
        "Importación %s de %s: %d nuevos, %d actualizados, %d sin cambios, %d antiguos, eventos %s",
        resumen.importacion_id, archivo, resumen.nuevos, resumen.actualizados,
        resumen.sin_cambios, resumen.omitidos_por_antiguos, dict(resumen.eventos),
    )
    return resumen


class _Cargador:
    """Estado de una carga: tickets y técnicos existentes precargados en memoria."""

    def __init__(self, conexion: sqlite3.Connection, franjas: Sequence[Franja], prioridad_p1: int):
        self.conexion = conexion
        self.franjas = franjas
        self.prioridad_p1 = prioridad_p1
        self.tecnicos = {
            fila["nombre_glpi"]: fila["id"]
            for fila in conexion.execute("SELECT id, nombre_glpi FROM tecnico")
        }
        self.tickets = {
            fila["id_glpi"]: fila for fila in conexion.execute(
                "SELECT id_glpi, estado, estado_codigo, prioridad, ultima_actualizacion, "
                "fecha_solucion, fecha_cierre, tipo_caso, tipo_caso_origen, hash_fila FROM ticket"
            )
        }
        self.tecnicos_por_ticket: dict[int, tuple[str, ...]] = {}
        for fila in conexion.execute(
            "SELECT tt.ticket_id, t.nombre_glpi FROM ticket_tecnico tt "
            "JOIN tecnico t ON t.id = tt.tecnico_id ORDER BY tt.ticket_id, tt.orden"
        ):
            self.tecnicos_por_ticket.setdefault(fila[0], ())
            self.tecnicos_por_ticket[fila[0]] += (fila[1],)
        self.escalados = {
            fila[0] for fila in conexion.execute(
                "SELECT DISTINCT ticket_id FROM ticket_evento WHERE tipo = ?", (ev.ESCALAMIENTO,)
            )
        }

    def cargar(
        self, filas: pd.DataFrame, resumen: ResumenImportacion, ahora: datetime,
        progreso: Progreso | None,
    ) -> None:
        total = len(filas)
        for numero, fila in enumerate(filas.to_dict("records"), start=1):
            self._cargar_fila(_normalizar(fila), resumen, ahora)
            if progreso and (numero % AVISAR_CADA == 0 or numero == total):
                progreso(numero, total)

    def _cargar_fila(self, fila: dict, resumen: ResumenImportacion, ahora: datetime) -> None:
        id_glpi = fila["id_glpi"]
        derivado = derivados.derivar(fila, self.franjas, self.prioridad_p1)
        guardado = self.tickets.get(id_glpi)
        if guardado is None:
            self._insertar(fila, derivado, resumen, ahora)
            resumen.nuevos += 1
            return
        ultima_guardada = _fecha(guardado["ultima_actualizacion"])
        if fila["ultima_actualizacion"] < ultima_guardada:
            resumen.omitidos_por_antiguos += 1
            return
        if derivado.hash_fila == guardado["hash_fila"]:
            self.conexion.execute(
                "UPDATE ticket SET ultima_importacion_id = ? WHERE id_glpi = ?",
                (resumen.importacion_id, id_glpi),
            )
            resumen.sin_cambios += 1
            return
        self._actualizar(fila, derivado, guardado, resumen, ahora)
        resumen.actualizados += 1

    # --- Nuevo ticket ---

    def _insertar(self, fila: dict, derivado, resumen: ResumenImportacion, ahora: datetime) -> None:
        id_glpi = fila["id_glpi"]
        principal_id = self._tecnico_id(derivado.tecnico_principal, ahora)
        nuevos = ev.eventos_de_transicion(None, fila["estado_codigo"])
        fechas = ev.aplicar_eventos(
            ev.FechasAproximadas(None, None), nuevos, fila["ultima_actualizacion"]
        )
        tuvo_escalamiento = ev.ESCALAMIENTO in nuevos
        self.conexion.execute(
            "INSERT INTO ticket (id_glpi, titulo, entidad, estado, estado_codigo, prioridad, "
            "prioridad_nivel, es_p1, fecha_apertura, ultima_actualizacion, fecha_solucion, "
            "fecha_cierre, autor, ubicacion, tecnico_principal_id, escalado, tipo_caso, "
            "tipo_caso_origen, turno_apertura, horas_resolucion, horas_hasta_cierre, hash_fila, "
            "primera_importacion_id, ultima_importacion_id) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'INFERIDO', ?, ?, ?, ?, ?, ?)",
            (
                id_glpi, fila["titulo"], fila["entidad"], fila["estado"], fila["estado_codigo"],
                fila["prioridad"], fila["prioridad_nivel"], int(derivado.es_p1),
                _iso(fila["fecha_apertura"]), _iso(fila["ultima_actualizacion"]),
                _iso(fechas.fecha_solucion), _iso(fechas.fecha_cierre), fila["autor"],
                fila["ubicacion"], principal_id, int(derivado.escalado),
                derivados.inferir_tipo_caso(derivado.es_p1, tuvo_escalamiento),
                derivado.turno_apertura,
                derivados.horas_entre(fila["fecha_apertura"], fechas.fecha_solucion),
                derivados.horas_entre(fila["fecha_apertura"], fechas.fecha_cierre),
                derivado.hash_fila, resumen.importacion_id, resumen.importacion_id,
            ),
        )
        self._guardar_tecnicos(id_glpi, fila["tecnicos"], ahora)
        self._registrar_eventos(
            id_glpi, nuevos, fila["ultima_actualizacion"], ev.PRIMERA_VEZ, principal_id, resumen
        )
        if tuvo_escalamiento:
            self.escalados.add(id_glpi)

    # --- Ticket existente con cambios ---

    def _actualizar(
        self, fila: dict, derivado, guardado: sqlite3.Row, resumen: ResumenImportacion,
        ahora: datetime,
    ) -> None:
        id_glpi = fila["id_glpi"]
        principal_id = self._tecnico_id(derivado.tecnico_principal, ahora)
        anteriores = self.tecnicos_por_ticket.get(id_glpi, ())
        for campo, antes, despues in (
            ("estado", guardado["estado"], fila["estado"]),
            ("tecnico", ", ".join(anteriores), ", ".join(fila["tecnicos"])),
            ("prioridad", guardado["prioridad"], fila["prioridad"]),
        ):
            if antes != despues:
                self.conexion.execute(
                    "INSERT INTO ticket_cambio (ticket_id, importacion_id, campo, valor_anterior, "
                    "valor_nuevo, detectado_en) VALUES (?, ?, ?, ?, ?, ?)",
                    (id_glpi, resumen.importacion_id, campo, antes or None, despues or None, _iso(ahora)),
                )
                resumen.cambios += 1

        nuevos = ev.eventos_de_transicion(guardado["estado_codigo"], fila["estado_codigo"])
        fechas = ev.aplicar_eventos(
            ev.FechasAproximadas(_fecha(guardado["fecha_solucion"]), _fecha(guardado["fecha_cierre"])),
            nuevos,
            fila["ultima_actualizacion"],
        )
        if ev.ESCALAMIENTO in nuevos:
            self.escalados.add(id_glpi)
        if guardado["tipo_caso_origen"] == ORIGEN_MANUAL:
            tipo_caso = guardado["tipo_caso"]
        else:
            tipo_caso = derivados.inferir_tipo_caso(derivado.es_p1, id_glpi in self.escalados)
        self.conexion.execute(
            "UPDATE ticket SET titulo = ?, entidad = ?, estado = ?, estado_codigo = ?, "
            "prioridad = ?, prioridad_nivel = ?, es_p1 = ?, ultima_actualizacion = ?, "
            "fecha_solucion = ?, fecha_cierre = ?, autor = ?, ubicacion = ?, "
            "tecnico_principal_id = ?, escalado = ?, tipo_caso = ?, horas_resolucion = ?, "
            "horas_hasta_cierre = ?, hash_fila = ?, ultima_importacion_id = ? WHERE id_glpi = ?",
            (
                fila["titulo"], fila["entidad"], fila["estado"], fila["estado_codigo"],
                fila["prioridad"], fila["prioridad_nivel"], int(derivado.es_p1),
                _iso(fila["ultima_actualizacion"]), _iso(fechas.fecha_solucion),
                _iso(fechas.fecha_cierre), fila["autor"], fila["ubicacion"], principal_id,
                int(derivado.escalado), tipo_caso,
                derivados.horas_entre(fila["fecha_apertura"], fechas.fecha_solucion),
                derivados.horas_entre(fila["fecha_apertura"], fechas.fecha_cierre),
                derivado.hash_fila, resumen.importacion_id, id_glpi,
            ),
        )
        if tuple(fila["tecnicos"]) != anteriores:
            self.conexion.execute("DELETE FROM ticket_tecnico WHERE ticket_id = ?", (id_glpi,))
            self._guardar_tecnicos(id_glpi, fila["tecnicos"], ahora)
        self._registrar_eventos(
            id_glpi, nuevos, fila["ultima_actualizacion"], ev.TRANSICION, principal_id, resumen
        )

    # --- Apoyo ---

    def _tecnico_id(self, nombre: str | None, ahora: datetime) -> int | None:
        """Id del técnico; si es nuevo se crea (el coordinador completa turno y estado)."""
        if nombre is None:
            return None
        if nombre not in self.tecnicos:
            cursor = self.conexion.execute(
                "INSERT INTO tecnico (nombre_glpi, nombre_mostrar, creado_en) VALUES (?, ?, ?)",
                (nombre, nombre, _iso(ahora)),
            )
            self.tecnicos[nombre] = cursor.lastrowid
        return self.tecnicos[nombre]

    def _guardar_tecnicos(self, id_glpi: int, tecnicos: tuple[str, ...], ahora: datetime) -> None:
        self.conexion.executemany(
            "INSERT INTO ticket_tecnico (ticket_id, tecnico_id, orden) VALUES (?, ?, ?)",
            [(id_glpi, self._tecnico_id(n, ahora), orden) for orden, n in enumerate(tecnicos, 1)],
        )
        self.tecnicos_por_ticket[id_glpi] = tuple(tecnicos)

    def _registrar_eventos(
        self, id_glpi: int, tipos: list[str], fecha: datetime, origen: str,
        tecnico_id: int | None, resumen: ResumenImportacion,
    ) -> None:
        self.conexion.executemany(
            "INSERT INTO ticket_evento (ticket_id, importacion_id, tipo, fecha_evento, origen, "
            "tecnico_id) VALUES (?, ?, ?, ?, ?, ?)",
            [(id_glpi, resumen.importacion_id, t, _iso(fecha), origen, tecnico_id) for t in tipos],
        )
        resumen.eventos.update(tipos)


def _normalizar(fila: dict) -> dict:
    """Convierte los tipos de pandas (Timestamp, Int64) a tipos de Python."""
    fila = dict(fila)
    for campo in ("fecha_apertura", "ultima_actualizacion"):
        fila[campo] = pd.Timestamp(fila[campo]).to_pydatetime()
    fila["id_glpi"] = int(fila["id_glpi"])
    fila["prioridad_nivel"] = int(fila["prioridad_nivel"])
    fila["tecnicos"] = tuple(fila["tecnicos"] or ())
    return fila
