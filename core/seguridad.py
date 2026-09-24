"""Usuarios, PIN, sesión y permisos por perfil (RNF-07, CA-08).

Los permisos se aplican aquí, en core/, y no solo ocultando botones en la interfaz.
Todos los usuarios tienen PIN; solo se guarda su hash bcrypt.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import bcrypt

from core import historial, reloj
from core.errores import ErrorAutenticacion, ErrorPermiso, ErrorValidacion

COORDINADOR = "COORDINADOR"
CONSULTA = "CONSULTA"
PERFILES = (COORDINADOR, CONSULTA)

LONGITUD_MINIMA_PIN = 4
LONGITUD_MAXIMA_PIN = 12
RONDAS_BCRYPT = 12

MENSAJE_SOLO_COORDINADOR = "Esta acción solo la puede hacer el coordinador."


INTENTOS_SIN_ESPERA = 5
ESPERA_INICIAL_SEGUNDOS = 30
ESPERA_MAXIMA_SEGUNDOS = 300


class ControlIntentos:
    """Espera creciente después de varios PIN incorrectos seguidos.

    No bloquea la cuenta: un bloqueo total podría dejar al coordinador sin acceso.
    Tras INTENTOS_SIN_ESPERA fallos, cada fallo exige esperar el doble que el
    anterior (30 s, 60 s, 120 s…, hasta 5 minutos). Un acierto reinicia la cuenta.
    """

    def __init__(self):
        self.fallos = 0
        self.bloqueado_hasta: datetime | None = None

    def segundos_restantes(self, ahora: datetime) -> int:
        if self.bloqueado_hasta is None or ahora >= self.bloqueado_hasta:
            return 0
        return int((self.bloqueado_hasta - ahora).total_seconds()) + 1

    def registrar_fallo(self, ahora: datetime) -> int:
        """Devuelve los segundos que hay que esperar antes del próximo intento."""
        self.fallos += 1
        if self.fallos < INTENTOS_SIN_ESPERA:
            return 0
        espera = min(
            ESPERA_INICIAL_SEGUNDOS * 2 ** (self.fallos - INTENTOS_SIN_ESPERA), ESPERA_MAXIMA_SEGUNDOS
        )
        self.bloqueado_hasta = ahora + timedelta(seconds=espera)
        return espera

    def registrar_acierto(self) -> None:
        self.fallos = 0
        self.bloqueado_hasta = None


@dataclass(frozen=True)
class Sesion:
    usuario_id: int
    nombre: str
    perfil: str
    tecnico_id: int | None

    @property
    def es_coordinador(self) -> bool:
        return self.perfil == COORDINADOR


# --- PIN ---

def validar_pin(pin: str) -> None:
    if not (pin.isdigit() and LONGITUD_MINIMA_PIN <= len(pin) <= LONGITUD_MAXIMA_PIN):
        raise ErrorValidacion(
            f"El PIN debe tener entre {LONGITUD_MINIMA_PIN} y {LONGITUD_MAXIMA_PIN} "
            "dígitos, solo números."
        )


def hash_pin(pin: str) -> str:
    validar_pin(pin)
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(RONDAS_BCRYPT)).decode("ascii")


def pin_correcto(pin: str, pin_hash: str) -> bool:
    return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("ascii"))


# --- Permisos ---

def exigir_coordinador(sesion: Sesion) -> None:
    if not sesion.es_coordinador:
        raise ErrorPermiso(MENSAJE_SOLO_COORDINADOR)


def tecnico_permitido(sesion: Sesion, tecnico_id: int | None) -> int | None:
    """Técnico cuyas métricas individuales puede consultar la sesión.

    - Coordinador: el pedido; None significa todos los técnicos.
    - Consulta con técnico asociado: solo el propio (None se interpreta como el propio).
    - Consulta sin técnico asociado (jefatura): ninguno; solo ve agregados del equipo.
    """
    if sesion.es_coordinador:
        return tecnico_id
    if sesion.tecnico_id is None:
        raise ErrorPermiso(
            "Su usuario no tiene un técnico asociado: puede ver los indicadores del "
            "equipo, pero no las métricas individuales."
        )
    if tecnico_id is not None and tecnico_id != sesion.tecnico_id:
        raise ErrorPermiso("Solo puede consultar sus propias métricas.")
    return sesion.tecnico_id


# --- Usuarios ---

def hay_usuarios(conexion: sqlite3.Connection) -> bool:
    """Si no hay ninguno, la interfaz abre el asistente de primera ejecución."""
    return conexion.execute("SELECT EXISTS (SELECT 1 FROM usuario)").fetchone()[0] == 1


def listar_usuarios_activos(conexion: sqlite3.Connection) -> list[sqlite3.Row]:
    """Para la pantalla de inicio de sesión: sin hashes."""
    return conexion.execute(
        "SELECT id, nombre, perfil FROM usuario WHERE activo = 1 ORDER BY nombre"
    ).fetchall()


def listar_usuarios(conexion: sqlite3.Connection, sesion: Sesion) -> list[sqlite3.Row]:
    exigir_coordinador(sesion)
    return conexion.execute(
        "SELECT u.id, u.nombre, u.perfil, u.tecnico_id, t.nombre_mostrar AS tecnico, "
        "u.activo, u.creado_en FROM usuario u LEFT JOIN tecnico t ON t.id = u.tecnico_id "
        "ORDER BY u.nombre"
    ).fetchall()


def iniciar_sesion(conexion: sqlite3.Connection, usuario_id: int, pin: str) -> Sesion:
    fila = conexion.execute(
        "SELECT id, nombre, perfil, tecnico_id, pin_hash, activo FROM usuario WHERE id = ?",
        (usuario_id,),
    ).fetchone()
    if fila is None or not fila["activo"]:
        raise ErrorAutenticacion("El usuario no existe o está inactivo.")
    if not pin_correcto(pin, fila["pin_hash"]):
        raise ErrorAutenticacion("PIN incorrecto.")
    return Sesion(fila["id"], fila["nombre"], fila["perfil"], fila["tecnico_id"])


def crear_usuario(
    conexion: sqlite3.Connection,
    sesion: Sesion | None,
    *,
    nombre: str,
    perfil: str,
    pin: str,
    tecnico_id: int | None = None,
) -> int:
    """Crea un usuario. Sin sesión solo se permite crear el primer coordinador."""
    if sesion is None:
        if hay_usuarios(conexion) or perfil != COORDINADOR:
            raise ErrorPermiso(MENSAJE_SOLO_COORDINADOR)
    else:
        exigir_coordinador(sesion)
    nombre = nombre.strip()
    if not nombre:
        raise ErrorValidacion("Escriba el nombre del usuario.")
    if perfil not in PERFILES:
        raise ErrorValidacion("El perfil debe ser Coordinador o Consulta.")
    if tecnico_id is not None and not _existe_tecnico(conexion, tecnico_id):
        raise ErrorValidacion("El técnico seleccionado no existe.")
    pin_hash = hash_pin(pin)
    try:
        with conexion:
            cursor = conexion.execute(
                "INSERT INTO usuario (nombre, perfil, tecnico_id, pin_hash, creado_en) "
                "VALUES (?, ?, ?, ?, ?)",
                (nombre, perfil, tecnico_id, pin_hash, reloj.ahora().isoformat(sep=" ")),
            )
            usuario_id = cursor.lastrowid
            historial.registrar(
                conexion,
                entidad="usuario",
                entidad_id=usuario_id,
                accion="CREAR",
                usuario_id=sesion.usuario_id if sesion else usuario_id,
                valor_nuevo=f"{nombre} ({perfil})",
            )
    except sqlite3.IntegrityError as error:
        raise ErrorValidacion(f"Ya existe un usuario llamado «{nombre}».") from error
    return usuario_id


def restablecer_pin(
    conexion: sqlite3.Connection, sesion: Sesion, usuario_id: int, pin_nuevo: str
) -> None:
    """El coordinador asigna un PIN nuevo a cualquier usuario."""
    exigir_coordinador(sesion)
    _guardar_pin(conexion, sesion, usuario_id, pin_nuevo, "RESTABLECER_PIN")


def cambiar_pin_propio(
    conexion: sqlite3.Connection, sesion: Sesion, pin_actual: str, pin_nuevo: str
) -> None:
    iniciar_sesion(conexion, sesion.usuario_id, pin_actual)
    _guardar_pin(conexion, sesion, sesion.usuario_id, pin_nuevo, "CAMBIAR_PIN")


def cambiar_estado_usuario(
    conexion: sqlite3.Connection, sesion: Sesion, usuario_id: int, activo: bool
) -> None:
    exigir_coordinador(sesion)
    fila = _usuario(conexion, usuario_id)
    if not activo and fila["perfil"] == COORDINADOR and fila["activo"]:
        coordinadores = conexion.execute(
            "SELECT COUNT(*) FROM usuario WHERE perfil = ? AND activo = 1", (COORDINADOR,)
        ).fetchone()[0]
        if coordinadores <= 1:
            raise ErrorValidacion("No se puede desactivar al único coordinador activo.")
    if bool(fila["activo"]) == activo:
        return
    with conexion:
        conexion.execute(
            "UPDATE usuario SET activo = ? WHERE id = ?", (int(activo), usuario_id)
        )
        historial.registrar(
            conexion,
            entidad="usuario",
            entidad_id=usuario_id,
            accion="ACTIVAR" if activo else "DESACTIVAR",
            usuario_id=sesion.usuario_id,
            campo="activo",
            valor_anterior=fila["activo"],
            valor_nuevo=int(activo),
        )


def _guardar_pin(
    conexion: sqlite3.Connection, sesion: Sesion, usuario_id: int, pin: str, accion: str
) -> None:
    _usuario(conexion, usuario_id)
    pin_hash = hash_pin(pin)
    with conexion:
        conexion.execute("UPDATE usuario SET pin_hash = ? WHERE id = ?", (pin_hash, usuario_id))
        # Nunca se registra el PIN ni su hash en el historial
        historial.registrar(
            conexion,
            entidad="usuario",
            entidad_id=usuario_id,
            accion=accion,
            usuario_id=sesion.usuario_id,
        )


def _usuario(conexion: sqlite3.Connection, usuario_id: int) -> sqlite3.Row:
    fila = conexion.execute(
        "SELECT id, perfil, activo FROM usuario WHERE id = ?", (usuario_id,)
    ).fetchone()
    if fila is None:
        raise ErrorValidacion("El usuario no existe.")
    return fila


def _existe_tecnico(conexion: sqlite3.Connection, tecnico_id: int) -> bool:
    return (
        conexion.execute("SELECT 1 FROM tecnico WHERE id = ?", (tecnico_id,)).fetchone()
        is not None
    )
