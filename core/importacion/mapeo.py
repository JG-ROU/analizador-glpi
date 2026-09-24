"""Mapeo de columnas, estados y prioridades, y perfiles de importación (IMP-01, CA-02).

El mapeo asocia cada campo interno a un encabezado del CSV. La autodetección
compara los encabezados sin tildes, mayúsculas ni signos contra una lista de
sinónimos. El usuario confirma el resultado y lo guarda como perfil reutilizable.
"""

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field, replace

import pandas as pd

from core import historial, reloj, seguridad
from core.dominio import ESTADOS, MAPEO_ESTADOS_GLPI, MAPEO_PRIORIDADES_GLPI
from core.errores import ErrorValidacion
from core.fuentes.fuente_csv import FormatoCSV
from core.seguridad import Sesion

SEPARADOR_MULTIVALOR_POR_DEFECTO = "\n"
NOMBRE_PERFIL_POR_DEFECTO = "Exportación GLPI"


@dataclass(frozen=True)
class CampoInterno:
    nombre: str
    etiqueta: str
    obligatorio: bool
    sinonimos: tuple[str, ...]  # ya normalizados con `normalizar`


CAMPOS_TICKET = (
    CampoInterno("id_glpi", "ID", True, ("id", "idglpi", "idticket", "numero", "ticket")),
    CampoInterno("titulo", "Título", True, ("titulo", "asunto", "nombre")),
    CampoInterno("entidad", "Entidad", False, ("entidad",)),
    CampoInterno("estado", "Estado", True, ("estado", "status")),
    CampoInterno("autor", "Autor", False, ("autorautor", "autor", "solicitante", "solicitantesolicitante")),
    CampoInterno(
        "tecnico", "Técnico asignado", True,
        ("asignadoatecnico", "asignadoa", "tecnico", "tecnicoasignado", "asignadoatecnicotecnico"),
    ),
    CampoInterno(
        "fecha_apertura", "Fecha de apertura", True,
        ("fechadeapertura", "fechaapertura", "apertura", "fechadecreacion"),
    ),
    CampoInterno(
        "ultima_actualizacion", "Última actualización", True,
        ("ultimaactualizacion", "fechadeultimaactualizacion", "ultimamodificacion", "actualizacion"),
    ),
    CampoInterno("prioridad", "Prioridad", True, ("prioridad", "priority")),
    CampoInterno("ubicacion", "Ubicación", False, ("ubicacion", "localizacion", "location")),
)
CAMPOS_POR_NOMBRE = {campo.nombre: campo for campo in CAMPOS_TICKET}


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y sin nada que no sea letra o número."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", sin_tildes.lower())


def _clave_valor(texto: str) -> str:
    """Clave para comparar valores de estado y prioridad: sin espacios sobrantes ni mayúsculas."""
    return " ".join(texto.split()).casefold()


@dataclass(frozen=True)
class Mapeo:
    columnas: dict[str, str]  # campo interno → encabezado del CSV
    estados: dict[str, str] = field(default_factory=lambda: dict(MAPEO_ESTADOS_GLPI))
    prioridades: dict[str, int] = field(default_factory=lambda: dict(MAPEO_PRIORIDADES_GLPI))

    def codigo_estado(self, texto: str) -> str | None:
        return _buscar(self.estados, texto)

    def nivel_prioridad(self, texto: str) -> int | None:
        return _buscar(self.prioridades, texto)


def _buscar(tabla: dict, texto: str):
    clave = _clave_valor(texto)
    for original, valor in tabla.items():
        if _clave_valor(original) == clave:
            return valor
    return None


@dataclass(frozen=True)
class PerfilImportacion:
    nombre: str
    separador: str
    codificacion: str
    formato_fecha: str
    mapeo: Mapeo
    separador_multivalor: str = SEPARADOR_MULTIVALOR_POR_DEFECTO
    id: int | None = None


# --- Autodetección ---

def proponer_columnas(encabezados: tuple[str, ...]) -> dict[str, str]:
    """Campo interno → encabezado, para los campos que se reconocen. Cada encabezado se usa una vez."""
    por_clave = {}
    for encabezado in encabezados:
        por_clave.setdefault(normalizar(encabezado), encabezado)
    propuesta: dict[str, str] = {}
    usados: set[str] = set()
    for campo in CAMPOS_TICKET:
        for sinonimo in campo.sinonimos:
            encabezado = por_clave.get(sinonimo)
            if encabezado and encabezado not in usados:
                propuesta[campo.nombre] = encabezado
                usados.add(encabezado)
                break
    return propuesta


def proponer_perfil(formato: FormatoCSV, nombre: str = NOMBRE_PERFIL_POR_DEFECTO) -> PerfilImportacion:
    """Perfil propuesto a partir del formato detectado; el usuario lo revisa y confirma."""
    return PerfilImportacion(
        nombre=nombre,
        separador=formato.separador,
        codificacion=formato.codificacion,
        formato_fecha=formato.formato_fecha or "",
        mapeo=Mapeo(columnas=proponer_columnas(formato.encabezados)),
    )


# --- Validación del mapeo ---

def errores_del_perfil(perfil: PerfilImportacion, encabezados: tuple[str, ...]) -> list[str]:
    """Problemas que impiden usar el perfil con un archivo; lista vacía si está bien."""
    errores = []
    if not perfil.nombre.strip():
        errores.append("Escriba un nombre para el perfil.")
    if not perfil.formato_fecha:
        errores.append("Indique el formato de fecha del archivo.")
    columnas = perfil.mapeo.columnas
    for campo in CAMPOS_TICKET:
        if campo.obligatorio and not columnas.get(campo.nombre):
            errores.append(f"Falta asociar el campo obligatorio «{campo.etiqueta}».")
    for nombre, encabezado in columnas.items():
        if nombre not in CAMPOS_POR_NOMBRE:
            errores.append(f"«{nombre}» no es un campo del ticket.")
        elif encabezado and encabezado not in encabezados:
            errores.append(
                f"La columna «{encabezado}» del campo «{CAMPOS_POR_NOMBRE[nombre].etiqueta}» "
                "no existe en el archivo."
            )
    usados = [e for e in columnas.values() if e]
    for encabezado in sorted({e for e in usados if usados.count(e) > 1}):
        errores.append(f"La columna «{encabezado}» está asociada a más de un campo.")
    for texto, codigo in perfil.mapeo.estados.items():
        if codigo not in ESTADOS:
            errores.append(f"El estado «{texto}» tiene un código inválido: «{codigo}».")
    for texto, nivel in perfil.mapeo.prioridades.items():
        if not isinstance(nivel, int) or not 1 <= nivel <= 6:
            errores.append(f"La prioridad «{texto}» debe tener un nivel entre 1 y 6.")
    return errores


def valores_no_mapeados(bloque: pd.DataFrame, mapeo: Mapeo) -> tuple[set[str], set[str]]:
    """Estados y prioridades presentes en el bloque que el mapeo no reconoce."""
    estados, prioridades = set(), set()
    columna_estado = mapeo.columnas.get("estado")
    if columna_estado in bloque:
        estados = {
            v.strip() for v in bloque[columna_estado].unique()
            if v.strip() and mapeo.codigo_estado(v) is None
        }
    columna_prioridad = mapeo.columnas.get("prioridad")
    if columna_prioridad in bloque:
        prioridades = {
            v.strip() for v in bloque[columna_prioridad].unique()
            if v.strip() and mapeo.nivel_prioridad(v) is None
        }
    return estados, prioridades


# --- Persistencia ---

def _a_fila(perfil: PerfilImportacion) -> dict:
    return {
        "nombre": perfil.nombre.strip(),
        "separador": perfil.separador,
        "codificacion": perfil.codificacion,
        "formato_fecha": perfil.formato_fecha,
        "separador_multivalor": perfil.separador_multivalor,
        "mapeo_json": json.dumps(perfil.mapeo.columnas, ensure_ascii=False, sort_keys=True),
        "mapeo_estados_json": json.dumps(perfil.mapeo.estados, ensure_ascii=False, sort_keys=True),
        "mapeo_prioridades_json": json.dumps(perfil.mapeo.prioridades, ensure_ascii=False, sort_keys=True),
    }


def _desde_fila(fila: sqlite3.Row) -> PerfilImportacion:
    return PerfilImportacion(
        id=fila["id"],
        nombre=fila["nombre"],
        separador=fila["separador"],
        codificacion=fila["codificacion"],
        formato_fecha=fila["formato_fecha"],
        separador_multivalor=fila["separador_multivalor"],
        mapeo=Mapeo(
            columnas=json.loads(fila["mapeo_json"]),
            estados=json.loads(fila["mapeo_estados_json"]),
            prioridades=json.loads(fila["mapeo_prioridades_json"]),
        ),
    )


def _descripcion(fila: dict) -> str:
    return json.dumps({k: v for k, v in fila.items() if k != "nombre"}, ensure_ascii=False, sort_keys=True)


def guardar_perfil(
    conexion: sqlite3.Connection,
    sesion: Sesion,
    perfil: PerfilImportacion,
    encabezados: tuple[str, ...],
) -> PerfilImportacion:
    """Crea el perfil o, si ya existe uno con ese nombre, lo actualiza. Solo el coordinador."""
    seguridad.exigir_coordinador(sesion)
    errores = errores_del_perfil(perfil, encabezados)
    if errores:
        raise ErrorValidacion("El perfil tiene problemas:\n- " + "\n- ".join(errores))
    fila = _a_fila(perfil)
    ahora = reloj.ahora().isoformat(sep=" ")
    anterior = conexion.execute(
        "SELECT * FROM perfil_importacion WHERE nombre = ?", (fila["nombre"],)
    ).fetchone()
    with conexion:
        if anterior is None:
            cursor = conexion.execute(
                "INSERT INTO perfil_importacion (nombre, separador, codificacion, formato_fecha, "
                "separador_multivalor, mapeo_json, mapeo_estados_json, mapeo_prioridades_json, "
                "creado_en, actualizado_en) VALUES (:nombre, :separador, :codificacion, "
                ":formato_fecha, :separador_multivalor, :mapeo_json, :mapeo_estados_json, "
                ":mapeo_prioridades_json, :ahora, :ahora)",
                {**fila, "ahora": ahora},
            )
            perfil_id = cursor.lastrowid
            historial.registrar(
                conexion, entidad="perfil_importacion", entidad_id=perfil_id, accion="CREAR",
                usuario_id=sesion.usuario_id, valor_nuevo=_descripcion(fila),
            )
        else:
            perfil_id = anterior["id"]
            valor_anterior = _descripcion(_a_fila(_desde_fila(anterior)))
            valor_nuevo = _descripcion(fila)
            if valor_anterior != valor_nuevo:
                conexion.execute(
                    "UPDATE perfil_importacion SET separador = :separador, codificacion = :codificacion, "
                    "formato_fecha = :formato_fecha, separador_multivalor = :separador_multivalor, "
                    "mapeo_json = :mapeo_json, mapeo_estados_json = :mapeo_estados_json, "
                    "mapeo_prioridades_json = :mapeo_prioridades_json, actualizado_en = :ahora "
                    "WHERE id = :id",
                    {**fila, "ahora": ahora, "id": perfil_id},
                )
                historial.registrar(
                    conexion, entidad="perfil_importacion", entidad_id=perfil_id,
                    accion="MODIFICAR", usuario_id=sesion.usuario_id,
                    valor_anterior=valor_anterior, valor_nuevo=valor_nuevo,
                )
    return replace(perfil, id=perfil_id, nombre=fila["nombre"])


def listar_perfiles(conexion: sqlite3.Connection) -> list[PerfilImportacion]:
    filas = conexion.execute("SELECT * FROM perfil_importacion ORDER BY nombre").fetchall()
    return [_desde_fila(f) for f in filas]


def obtener_perfil(conexion: sqlite3.Connection, perfil_id: int) -> PerfilImportacion:
    fila = conexion.execute(
        "SELECT * FROM perfil_importacion WHERE id = ?", (perfil_id,)
    ).fetchone()
    if fila is None:
        raise ErrorValidacion("El perfil de importación no existe.")
    return _desde_fila(fila)


def buscar_perfil_compatible(
    conexion: sqlite3.Connection, encabezados: tuple[str, ...]
) -> PerfilImportacion | None:
    """El perfil usado más recientemente cuyas columnas existen todas en el archivo."""
    filas = conexion.execute(
        "SELECT p.* FROM perfil_importacion p LEFT JOIN importacion i ON i.perfil_id = p.id "
        "GROUP BY p.id ORDER BY MAX(COALESCE(i.fecha, '')) DESC, p.actualizado_en DESC"
    ).fetchall()
    for fila in filas:
        perfil = _desde_fila(fila)
        if all(e in encabezados for e in perfil.mapeo.columnas.values() if e):
            return perfil
    return None


def eliminar_perfil(conexion: sqlite3.Connection, sesion: Sesion, perfil_id: int) -> None:
    seguridad.exigir_coordinador(sesion)
    perfil = obtener_perfil(conexion, perfil_id)
    usado = conexion.execute(
        "SELECT 1 FROM importacion WHERE perfil_id = ? LIMIT 1", (perfil_id,)
    ).fetchone()
    if usado:
        raise ErrorValidacion(
            f"El perfil «{perfil.nombre}» ya se usó en importaciones y no se puede eliminar."
        )
    with conexion:
        conexion.execute("DELETE FROM perfil_importacion WHERE id = ?", (perfil_id,))
        historial.registrar(
            conexion, entidad="perfil_importacion", entidad_id=perfil_id, accion="ELIMINAR",
            usuario_id=sesion.usuario_id, valor_anterior=perfil.nombre,
        )
