"""Importación del CSV de seguimientos y tareas (spec 03, Fase 3).

Una fila por nota. Se mapean las columnas como en los tickets y se guarda un perfil
con el prefijo «Seguimientos:». Cada nota se identifica por una huella (ticket,
fecha, autor, tipo y contenido), así que reimportar no duplica nada. La etiqueta
([DIAG], [ESC]…) se extrae del inicio del contenido. Las notas de tickets que no
están importados se informan y no se cargan.
"""

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from core import historial, reloj, seguridad
from core.db import respaldo
from core.errores import ErrorAplicacion, ErrorValidacion
from core.fuentes.base import COLUMNA_FILA
from core.fuentes.fuente_csv import FormatoCSV
from core.importacion.mapeo import CampoInterno, normalizar
from core.importacion.validacion import ADVERTENCIA, ERROR, VALIDA, formato_legible, leer_fecha, normalizar_id
from core.seguridad import Sesion

TIPO_SEGUIMIENTOS = "SEGUIMIENTOS"
PREFIJO_PERFIL = "Seguimientos: "
SEGUIMIENTO, TAREA, SOLUCION = "SEGUIMIENTO", "TAREA", "SOLUCION"
_ETIQUETA = re.compile(r"^\s*\[([A-Z0-9-]+)[^\]]*\]")
_HORAS_MINUTOS = re.compile(r"^(\d+):(\d{1,2})$")
_TEXTO_DURACION = re.compile(r"(?:(\d+)\s*h\w*)?\s*(?:(\d+)\s*m\w*)?", re.IGNORECASE)
_VERDADERO = {"si", "sí", "1", "true", "yes", "verdadero", "x"}

CAMPOS_SEGUIMIENTO = (
    CampoInterno("ticket_id", "ID del ticket", True, ("iddelticket", "idticket", "ticket", "ticketid", "id")),
    CampoInterno("fecha", "Fecha", True, ("fecha", "fechadecreacion", "fechadelseguimiento", "fechadelanota")),
    CampoInterno("autor", "Autor", False, ("autor", "escritor", "usuario", "tecnico")),
    CampoInterno("tipo", "Tipo (seguimiento / tarea / solución)", False, ("tipo", "tipodenota", "clase")),
    CampoInterno("privado", "Privado", False, ("privado", "esprivado", "privada")),
    CampoInterno("contenido", "Contenido", True, ("contenido", "descripcion", "texto", "seguimiento", "nota")),
    CampoInterno("categoria_tarea", "Categoría de tarea", False, ("categoriadetarea", "categoria", "categoriatarea")),
    CampoInterno("duracion", "Duración (minutos)", False, ("duracion", "duraciontotal", "tiempo", "duracionminutos")),
)
TIPOS_TEXTO = {"seguimiento": SEGUIMIENTO, "tarea": TAREA, "solucion": SOLUCION, "solución": SOLUCION}


def etiqueta_de(contenido: str) -> str | None:
    """«[DIAG] 10:30 Hice…» → «DIAG»; «[RECORDATORIO n.º 1/2]» → «RECORDATORIO»."""
    coincidencia = _ETIQUETA.match(contenido or "")
    return coincidencia.group(1) if coincidencia else None


def leer_duracion(texto: str) -> float | None:
    """Minutos: «90», «1:30» o «1 hora 30 minutos». None si no se entiende."""
    texto = (texto or "").strip().lower()
    if not texto:
        return None
    if texto.replace(".", "", 1).replace(",", "", 1).isdigit():
        return float(texto.replace(",", "."))
    if coincidencia := _HORAS_MINUTOS.match(texto):
        return int(coincidencia.group(1)) * 60 + int(coincidencia.group(2))
    coincidencia = _TEXTO_DURACION.fullmatch(texto)
    if coincidencia and any(coincidencia.groups()):
        return int(coincidencia.group(1) or 0) * 60 + int(coincidencia.group(2) or 0)
    return None


def proponer_columnas(encabezados: tuple[str, ...]) -> dict[str, str]:
    por_clave = {normalizar(e): e for e in encabezados}
    propuesta, usados = {}, set()
    for campo in CAMPOS_SEGUIMIENTO:
        for sinonimo in campo.sinonimos:
            encabezado = por_clave.get(sinonimo)
            if encabezado and encabezado not in usados:
                propuesta[campo.nombre] = encabezado
                usados.add(encabezado)
                break
    return propuesta


@dataclass
class PerfilSeguimientos:
    nombre: str
    formato: FormatoCSV
    formato_fecha: str
    columnas: dict[str, str]

    def errores(self) -> list[str]:
        errores = []
        for campo in CAMPOS_SEGUIMIENTO:
            if campo.obligatorio and not self.columnas.get(campo.nombre):
                errores.append(f"Falta asociar el campo obligatorio «{campo.etiqueta}».")
        for nombre, encabezado in self.columnas.items():
            if encabezado not in self.formato.encabezados:
                errores.append(f"La columna «{encabezado}» no existe en el archivo.")
        if not self.formato_fecha:
            errores.append("Indique el formato de fecha del archivo.")
        return errores


# --- Validación ---

@dataclass
class ResultadoSeguimientos:
    filas: pd.DataFrame
    originales: pd.DataFrame

    def conteo(self, resultado: str) -> int:
        return int((self.filas["resultado"] == resultado).sum())

    @property
    def cargables(self) -> pd.DataFrame:
        return self.filas[self.filas["resultado"] != ERROR]


def validar(conexion: sqlite3.Connection, bloques: Iterable[pd.DataFrame], perfil: PerfilSeguimientos) -> ResultadoSeguimientos:
    errores = perfil.errores()
    if errores:
        raise ErrorValidacion("El perfil tiene problemas:\n- " + "\n- ".join(errores))
    tickets = {f[0] for f in conexion.execute("SELECT id_glpi FROM ticket")}
    interpretadas, originales = [], []
    for bloque in bloques:
        originales.append(bloque)
        columnas = {c.nombre: perfil.columnas.get(c.nombre) for c in CAMPOS_SEGUIMIENTO}
        for i, numero in enumerate(bloque[COLUMNA_FILA]):
            crudo = {n: (bloque[col].iloc[i] if col else "") for n, col in columnas.items()}
            interpretadas.append(_validar_fila(numero, crudo, perfil.formato_fecha, tickets))
    filas = pd.DataFrame(interpretadas, columns=[
        COLUMNA_FILA, "ticket_id", "fecha", "autor", "tipo", "privado", "contenido", "categoria_tarea",
        "duracion_min", "etiqueta", "resultado", "motivos",
    ])
    return ResultadoSeguimientos(filas, pd.concat(originales, ignore_index=True) if originales else pd.DataFrame())


def _validar_fila(numero: int, crudo: dict, formato_fecha: str, tickets: set[int]) -> dict:
    errores, advertencias = [], []
    ticket_id = normalizar_id(crudo["ticket_id"])
    if ticket_id is None:
        errores.append(f"ID de ticket inválido: «{crudo['ticket_id'].strip()}»")
    elif ticket_id not in tickets:
        errores.append(f"El ticket {ticket_id} no está importado: importe primero el CSV de tickets")
    fecha = leer_fecha(crudo["fecha"], formato_fecha) if crudo["fecha"].strip() else None
    if fecha is None:
        errores.append(f"Fecha inválida: «{crudo['fecha'].strip()}» (formato esperado {formato_legible(formato_fecha)})")
    contenido = crudo["contenido"].strip()
    if not contenido:
        errores.append("Contenido vacío")
    tipo_texto = normalizar(crudo["tipo"]) if crudo["tipo"].strip() else ""
    tipo = next((v for k, v in TIPOS_TEXTO.items() if normalizar(k) == tipo_texto), None)
    if tipo is None:
        if tipo_texto:
            advertencias.append(f"Tipo desconocido «{crudo['tipo'].strip()}»: se toma como seguimiento")
        tipo = SEGUIMIENTO
    duracion = leer_duracion(crudo["duracion"])
    if crudo["duracion"].strip() and duracion is None:
        advertencias.append(f"Duración no reconocida: «{crudo['duracion'].strip()}»")
    resultado = ERROR if errores else ADVERTENCIA if advertencias else VALIDA
    return {
        COLUMNA_FILA: numero, "ticket_id": ticket_id, "fecha": fecha, "autor": " ".join(crudo["autor"].split()) or None,
        "tipo": tipo, "privado": int(crudo["privado"].strip().lower() in _VERDADERO), "contenido": contenido,
        "categoria_tarea": crudo["categoria_tarea"].strip() or None, "duracion_min": duracion,
        "etiqueta": etiqueta_de(contenido), "resultado": resultado, "motivos": "; ".join(errores + advertencias),
    }


# --- Carga ---

@dataclass
class ResumenSeguimientos:
    importacion_id: int
    nuevos: int = 0
    repetidos: int = 0
    filas_error: int = 0
    tickets: set = field(default_factory=set)


def huella(fila: dict) -> str:
    partes = [str(fila["ticket_id"]), fila["fecha"].isoformat(sep=" "), fila["autor"] or "", fila["tipo"], fila["contenido"]]
    return hashlib.sha256("\x1f".join(partes).encode("utf-8")).hexdigest()


def importar(conexion: sqlite3.Connection, sesion: Sesion, *, archivo: str, hash_archivo: str,
             perfil: PerfilSeguimientos, validacion: ResultadoSeguimientos, carpeta_respaldos: Path,
             retencion_respaldos: int) -> ResumenSeguimientos:
    seguridad.exigir_coordinador(sesion)
    previa = conexion.execute("SELECT fecha, archivo FROM importacion WHERE tipo = ? AND hash = ?",
                              (TIPO_SEGUIMIENTOS, hash_archivo)).fetchone()
    if previa:
        raise ErrorValidacion(f"Este archivo de seguimientos ya se importó el {previa['fecha'][:16]} («{previa['archivo']}»).")
    ruta_respaldo = respaldo.respaldar_antes_de_importar(conexion, carpeta_respaldos, retencion_respaldos)
    cargables = validacion.cargables
    fechas = cargables["fecha"].dropna()
    ahora = reloj.ahora().isoformat(sep=" ")
    try:
        with conexion:
            perfil_id = _guardar_perfil(conexion, sesion, perfil)
            cursor = conexion.execute(
                "INSERT INTO importacion (tipo, archivo, hash, perfil_id, usuario_id, fecha, filas_leidas, filas_validas, "
                "filas_advertencia, filas_error, fecha_min, fecha_max) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (TIPO_SEGUIMIENTOS, archivo, hash_archivo, perfil_id, sesion.usuario_id, ahora, len(validacion.filas),
                 validacion.conteo(VALIDA), validacion.conteo(ADVERTENCIA), validacion.conteo(ERROR),
                 None if fechas.empty else fechas.min().isoformat(sep=" "),
                 None if fechas.empty else fechas.max().isoformat(sep=" ")),
            )
            resumen = ResumenSeguimientos(cursor.lastrowid, filas_error=validacion.conteo(ERROR))
            for fila in cargables.to_dict("records"):
                fila["fecha"] = pd.Timestamp(fila["fecha"]).to_pydatetime()
                fila["ticket_id"] = int(fila["ticket_id"])
                insertada = conexion.execute(
                    "INSERT OR IGNORE INTO seguimiento (ticket_id, fecha, autor, tipo, privado, contenido, categoria_tarea, "
                    "duracion_min, etiqueta, huella, importacion_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (fila["ticket_id"], fila["fecha"].isoformat(sep=" "), fila["autor"], fila["tipo"], fila["privado"],
                     fila["contenido"], fila["categoria_tarea"],
                     None if pd.isna(fila["duracion_min"]) else float(fila["duracion_min"]),
                     fila["etiqueta"], huella(fila), resumen.importacion_id),
                ).rowcount
                resumen.nuevos += insertada
                resumen.repetidos += 1 - insertada
                resumen.tickets.add(fila["ticket_id"])
            historial.registrar(conexion, entidad="importacion", entidad_id=resumen.importacion_id, accion="IMPORTAR",
                                usuario_id=sesion.usuario_id, valor_nuevo=archivo,
                                nota=f"Seguimientos: {resumen.nuevos} nuevos, {resumen.repetidos} ya existían, "
                                     f"{resumen.filas_error} filas con error")
    except sqlite3.Error as error:
        raise ErrorAplicacion("La importación de seguimientos no se completó y no se guardó ningún dato "
                              f"(respaldo: {ruta_respaldo.name}).", detalle=repr(error)) from error
    return resumen


def _guardar_perfil(conexion: sqlite3.Connection, sesion: Sesion, perfil: PerfilSeguimientos) -> int:
    nombre = perfil.nombre if perfil.nombre.startswith(PREFIJO_PERFIL) else PREFIJO_PERFIL + perfil.nombre
    datos = (perfil.formato.separador, perfil.formato.codificacion, perfil.formato_fecha, "\n",
             json.dumps(perfil.columnas, ensure_ascii=False, sort_keys=True), "{}", "{}")
    fila = conexion.execute("SELECT id FROM perfil_importacion WHERE nombre = ?", (nombre,)).fetchone()
    ahora = reloj.ahora().isoformat(sep=" ")
    if fila:
        conexion.execute(
            "UPDATE perfil_importacion SET separador = ?, codificacion = ?, formato_fecha = ?, separador_multivalor = ?, "
            "mapeo_json = ?, mapeo_estados_json = ?, mapeo_prioridades_json = ?, actualizado_en = ? WHERE id = ?",
            (*datos, ahora, fila["id"]),
        )
        return fila["id"]
    cursor = conexion.execute(
        "INSERT INTO perfil_importacion (nombre, separador, codificacion, formato_fecha, separador_multivalor, mapeo_json, "
        "mapeo_estados_json, mapeo_prioridades_json, creado_en, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (nombre, *datos, ahora, ahora),
    )
    historial.registrar(conexion, entidad="perfil_importacion", entidad_id=cursor.lastrowid, accion="CREAR",
                        usuario_id=sesion.usuario_id, valor_nuevo=nombre)
    return cursor.lastrowid


def perfil_guardado(conexion: sqlite3.Connection, formato: FormatoCSV) -> PerfilSeguimientos | None:
    """El perfil de seguimientos guardado cuyas columnas existen en el archivo."""
    for fila in conexion.execute("SELECT * FROM perfil_importacion WHERE nombre LIKE ? ORDER BY actualizado_en DESC",
                                 (PREFIJO_PERFIL + "%",)):
        columnas = json.loads(fila["mapeo_json"])
        if all(c in formato.encabezados for c in columnas.values()):
            return PerfilSeguimientos(fila["nombre"], formato, fila["formato_fecha"], columnas)
    return None


def proponer_perfil(formato: FormatoCSV) -> PerfilSeguimientos:
    return PerfilSeguimientos(PREFIJO_PERFIL + "Exportación GLPI", formato, formato.formato_fecha or "",
                              proponer_columnas(formato.encabezados))


def de_ticket(conexion: sqlite3.Connection, ticket_id: int) -> list[sqlite3.Row]:
    return conexion.execute(
        "SELECT * FROM seguimiento WHERE ticket_id = ? ORDER BY fecha, id", (ticket_id,)
    ).fetchall()
