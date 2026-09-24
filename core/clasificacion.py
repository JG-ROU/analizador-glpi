"""Clasificación manual de tickets y catálogo de estaciones (IMP-07, CA-23).

La exportación no trae estación, categoría, causa ni tipo de solución: el
coordinador los asigna aquí. La clasificación vive en `ticket_clasificacion`,
que la importación nunca toca, y cada cambio queda en el historial.
"""

import sqlite3
from dataclasses import dataclass

import pandas as pd

from core import historial, reloj, seguridad
from core.analisis.periodos import Periodo
from core.errores import ErrorValidacion
from core.seguridad import Sesion
from core.texto import normalizar_nombre, ultimo_nivel

ESTACION = "estacion_id"
CATEGORIA = "categoria_codigo"
CAUSA = "causa_codigo"
TIPO_SOLUCION = "tipo_solucion_codigo"
CAMPOS = (ESTACION, CATEGORIA, CAUSA, TIPO_SOLUCION)
ETIQUETAS = {ESTACION: "Estación", CATEGORIA: "Categoría", CAUSA: "Causa", TIPO_SOLUCION: "Tipo de solución"}
_TABLA_CATALOGO = {  # campo → (tabla, columna clave, columna nombre)
    ESTACION: ("estacion", "id", "nombre"),
    CATEGORIA: ("categoria", "codigo", "nivel2"),
    CAUSA: ("causa", "codigo", "nombre"),
    TIPO_SOLUCION: ("tipo_solucion", "codigo", "nombre"),
}

PENDIENTES = "PENDIENTES"
TODOS = "TODOS"


@dataclass(frozen=True)
class Opcion:
    valor: object
    texto: str


# --- Catálogos ---

def opciones(conexion: sqlite3.Connection, campo: str) -> list[Opcion]:
    """Valores activos de un catálogo para las listas desplegables."""
    if campo == ESTACION:
        filas = conexion.execute(
            "SELECT id, nombre, cliente FROM estacion WHERE activo = 1 ORDER BY nombre"
        ).fetchall()
        return [Opcion(f["id"], f["nombre"] + (f" ({f['cliente']})" if f["cliente"] else "")) for f in filas]
    if campo == CATEGORIA:
        filas = conexion.execute(
            "SELECT codigo, COALESCE(nivel3, nivel2) AS nombre FROM categoria WHERE activo = 1 ORDER BY codigo"
        ).fetchall()
        return [Opcion(f["codigo"], f["nombre"]) for f in filas]
    tabla = _TABLA_CATALOGO[campo][0]
    filas = conexion.execute(f"SELECT codigo, nombre FROM {tabla} WHERE activo = 1 ORDER BY codigo").fetchall()
    return [Opcion(f["codigo"], f"{f['codigo']} {f['nombre']}") for f in filas]


def listar_estaciones(conexion: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexion.execute(
        "SELECT e.*, (SELECT COUNT(*) FROM ticket_clasificacion c WHERE c.estacion_id = e.id) AS tickets "
        "FROM estacion e ORDER BY e.nombre"
    ).fetchall()


def guardar_estacion(
    conexion: sqlite3.Connection, sesion: Sesion, *, nombre: str, cliente: str | None = None,
    incluir_segmov: bool = True, activo: bool = True, estacion_id: int | None = None,
) -> int:
    """Crea o modifica una estación del catálogo, con historial."""
    seguridad.exigir_coordinador(sesion)
    nombre = " ".join(nombre.split())
    if not nombre:
        raise ErrorValidacion("Escriba el nombre de la estación.")
    cliente = " ".join((cliente or "").split()) or None
    nuevos = {"nombre": nombre, "cliente": cliente, "incluir_segmov": int(incluir_segmov), "activo": int(activo)}
    try:
        with conexion:
            if estacion_id is None:
                cursor = conexion.execute(
                    "INSERT INTO estacion (nombre, cliente, incluir_segmov, activo, creado_en) VALUES (?, ?, ?, ?, ?)",
                    (nombre, cliente, nuevos["incluir_segmov"], nuevos["activo"], reloj.ahora().isoformat(sep=" ")),
                )
                estacion_id = cursor.lastrowid
                historial.registrar(conexion, entidad="estacion", entidad_id=estacion_id, accion="CREAR",
                                    usuario_id=sesion.usuario_id, valor_nuevo=nombre)
                return estacion_id
            fila = conexion.execute("SELECT * FROM estacion WHERE id = ?", (estacion_id,)).fetchone()
            if fila is None:
                raise ErrorValidacion("La estación no existe.")
            for campo, valor in nuevos.items():
                if fila[campo] != valor:
                    conexion.execute(f"UPDATE estacion SET {campo} = ? WHERE id = ?", (valor, estacion_id))
                    historial.registrar(conexion, entidad="estacion", entidad_id=estacion_id, accion="MODIFICAR",
                                        usuario_id=sesion.usuario_id, campo=campo,
                                        valor_anterior=fila[campo], valor_nuevo=valor)
    except sqlite3.IntegrityError as error:
        raise ErrorValidacion(f"Ya existe una estación llamada «{nombre}».") from error
    return estacion_id


# --- Clasificación ---

def _nombre_valor(conexion: sqlite3.Connection, campo: str, valor) -> str | None:
    if valor is None:
        return None
    tabla, clave, nombre = _TABLA_CATALOGO[campo]
    fila = conexion.execute(f"SELECT {nombre} FROM {tabla} WHERE {clave} = ?", (valor,)).fetchone()
    if fila is None:
        raise ErrorValidacion(f"El valor elegido para «{ETIQUETAS[campo]}» no existe en el catálogo.")
    return f"{valor} {fila[0]}" if campo != ESTACION else fila[0]


def clasificar(conexion: sqlite3.Connection, sesion: Sesion, ticket_ids: list[int], cambios: dict) -> int:
    """Asigna los valores de `cambios` (campo → valor o None para quitar) a los tickets.

    Solo se tocan los campos presentes en `cambios`. Devuelve cuántos tickets cambiaron.
    """
    seguridad.exigir_coordinador(sesion)
    desconocidos = set(cambios) - set(CAMPOS)
    if desconocidos:
        raise ErrorValidacion(f"Campos de clasificación desconocidos: {', '.join(sorted(desconocidos))}.")
    nombres = {campo: _nombre_valor(conexion, campo, valor) for campo, valor in cambios.items()}
    ahora = reloj.ahora().isoformat(sep=" ")
    modificados = 0
    with conexion:
        for ticket_id in ticket_ids:
            if conexion.execute("SELECT 1 FROM ticket WHERE id_glpi = ?", (ticket_id,)).fetchone() is None:
                raise ErrorValidacion(f"El ticket {ticket_id} no existe.")
            actual = conexion.execute(
                "SELECT * FROM ticket_clasificacion WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
            diferencias = {c: v for c, v in cambios.items() if (actual[c] if actual else None) != v}
            if not diferencias:
                continue
            if actual is None:
                conexion.execute(
                    "INSERT INTO ticket_clasificacion (ticket_id, actualizado_en, usuario_id) VALUES (?, ?, ?)",
                    (ticket_id, ahora, sesion.usuario_id),
                )
            for campo, valor in diferencias.items():
                conexion.execute(
                    f"UPDATE ticket_clasificacion SET {campo} = ?, actualizado_en = ?, usuario_id = ? "
                    "WHERE ticket_id = ?",
                    (valor, ahora, sesion.usuario_id, ticket_id),
                )
                historial.registrar(
                    conexion, entidad="ticket_clasificacion", entidad_id=ticket_id, accion="CLASIFICAR",
                    usuario_id=sesion.usuario_id, campo=ETIQUETAS[campo],
                    valor_anterior=_nombre_valor(conexion, campo, actual[campo]) if actual else None,
                    valor_nuevo=nombres[campo],
                )
            modificados += 1
    return modificados


def sugerir_estaciones(conexion: sqlite3.Connection, ticket_ids: list[int]) -> dict[int, int]:
    """Ticket → estación cuyo nombre coincide con el último nivel de su Ubicación.

    Solo propone; no guarda nada. Omite los tickets que ya tienen estación.
    """
    por_nombre = {
        normalizar_nombre(f["nombre"]): f["id"]
        for f in conexion.execute("SELECT id, nombre FROM estacion WHERE activo = 1")
    }
    sugerencias = {}
    for ticket_id in ticket_ids:
        fila = conexion.execute(
            "SELECT t.ubicacion, c.estacion_id FROM ticket t "
            "LEFT JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi WHERE t.id_glpi = ?",
            (ticket_id,),
        ).fetchone()
        if fila is None or fila["estacion_id"] is not None:
            continue
        nivel = ultimo_nivel(fila["ubicacion"])
        if nivel and normalizar_nombre(nivel) in por_nombre:
            sugerencias[ticket_id] = por_nombre[normalizar_nombre(nivel)]
    return sugerencias


COLUMNAS_LISTA = (
    "ID", "Título", "Estado", "Prioridad", "Apertura", "Ubicación (GLPI)",
    "Estación", "Categoría", "Causa", "Tipo de solución", "Pendiente",
)


def listar(conexion: sqlite3.Connection, sesion: Sesion, periodo: Periodo, vista: str = PENDIENTES) -> pd.DataFrame:
    """Tickets para clasificar. PENDIENTES: les falta algún campo (primero los resueltos)."""
    seguridad.exigir_coordinador(sesion)
    incompleto = ("(c.ticket_id IS NULL OR c.estacion_id IS NULL OR c.categoria_codigo IS NULL "
                  "OR c.causa_codigo IS NULL OR c.tipo_solucion_codigo IS NULL)")
    condicion = f"WHERE {incompleto}" if vista == PENDIENTES else "WHERE t.fecha_apertura >= ? AND t.fecha_apertura < ?"
    valores = [] if vista == PENDIENTES else [periodo.inicio.isoformat(sep=" "), periodo.fin.isoformat(sep=" ")]
    filas = conexion.execute(
        "SELECT t.id_glpi, t.titulo, t.estado, t.prioridad, t.fecha_apertura, t.ubicacion, t.estado_codigo, "
        "e.nombre AS estacion, c.categoria_codigo, c.causa_codigo, c.tipo_solucion_codigo, "
        f"{incompleto} AS pendiente FROM ticket t "
        "LEFT JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
        f"LEFT JOIN estacion e ON e.id = c.estacion_id {condicion} "
        "ORDER BY t.estado_codigo IN ('RESUELTO', 'CERRADO') DESC, t.fecha_apertura DESC",
        valores,
    ).fetchall()
    return pd.DataFrame(
        [
            {
                "ID": f["id_glpi"], "Título": f["titulo"], "Estado": f["estado"], "Prioridad": f["prioridad"],
                "Apertura": f["fecha_apertura"][:16], "Ubicación (GLPI)": f["ubicacion"],
                "Estación": f["estacion"], "Categoría": f["categoria_codigo"], "Causa": f["causa_codigo"],
                "Tipo de solución": f["tipo_solucion_codigo"], "Pendiente": "Sí" if f["pendiente"] else "No",
            }
            for f in filas
        ],
        columns=list(COLUMNAS_LISTA),
    )
