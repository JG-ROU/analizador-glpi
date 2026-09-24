"""Cambios de configuración hechos por el coordinador (PAN-13), siempre con historial.

Cubre parámetros, umbrales de KPIs, técnicos, festivos y franjas de turno. Cada
cambio y su registro en el historial se guardan en la misma transacción (RNF-09).
"""

import configparser
import sqlite3
from datetime import date, datetime
from pathlib import Path

from core import historial, parametros, seguridad
from core.analisis import calendario, condiciones
from core.analisis.kpis import CAMPOS_TIEMPO, TIPOS_CALCULO, TIPOS_TIEMPO, UNIDAD_POR_TIPO
from core.analisis.semaforo import MAYOR_MEJOR, MENOR_MEJOR
from core.config import NOMBRE_ARCHIVO
from core.dominio import TURNOS_TECNICO
from core.errores import ErrorConfiguracion, ErrorValidacion
from core.importacion import derivados, eventos as ev
from core.seguridad import Sesion
from core.turnos import Franja, interpretar_franja, validar_franjas

# Parámetros que pueden quedar vacíos: los define el coordinador cuando tenga el dato
GRUPOS_OPCIONALES = ("SLA", "Semáforo de tiempo de resolución")
CAMPOS_KPI_EDITABLES = (
    "umbral_verde", "umbral_amarillo", "meta", "visible_dashboard", "orden", "critico",
)


# --- Parámetros ---

def listar_parametros(conexion: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexion.execute("SELECT * FROM parametro ORDER BY grupo, clave").fetchall()


def _validar_valor(fila: sqlite3.Row, texto: str) -> str | None:
    if fila["tipo"] == "TEXTO":
        return " ".join(texto.split()) or None
    texto = texto.strip().replace(",", ".")
    if not texto:
        if fila["grupo"] in GRUPOS_OPCIONALES:
            return None
        raise ErrorValidacion(f"El parámetro «{fila['clave']}» no puede quedar vacío.")
    try:
        numero = int(texto) if fila["tipo"] == "ENTERO" else float(texto)
    except ValueError:
        tipo = "un número entero" if fila["tipo"] == "ENTERO" else "un número"
        raise ErrorValidacion(f"El parámetro «{fila['clave']}» debe ser {tipo}.") from None
    if fila["minimo"] is not None and numero < fila["minimo"]:
        raise ErrorValidacion(f"El parámetro «{fila['clave']}» debe ser mayor o igual a {fila['minimo']:g}.")
    if fila["maximo"] is not None and numero > fila["maximo"]:
        raise ErrorValidacion(f"El parámetro «{fila['clave']}» debe ser menor o igual a {fila['maximo']:g}.")
    return f"{numero:g}"  # 24.0 → "24", igual que las semillas


def actualizar_parametro(conexion: sqlite3.Connection, sesion: Sesion, clave: str, texto: str) -> None:
    seguridad.exigir_coordinador(sesion)
    fila = conexion.execute("SELECT * FROM parametro WHERE clave = ?", (clave,)).fetchone()
    if fila is None:
        raise ErrorValidacion(f"No existe el parámetro «{clave}».")
    nuevo = _validar_valor(fila, texto)
    if nuevo == fila["valor"]:
        return
    with conexion:
        conexion.execute("UPDATE parametro SET valor = ? WHERE clave = ?", (nuevo, clave))
        historial.registrar(
            conexion, entidad="parametro", entidad_id=clave, accion="MODIFICAR",
            usuario_id=sesion.usuario_id, campo="valor", valor_anterior=fila["valor"], valor_nuevo=nuevo,
        )
        if clave == "prioridad_p1":
            recalcular_p1(conexion, int(nuevo))


def recalcular_p1(conexion: sqlite3.Connection, prioridad_p1: int) -> None:
    """Recalcula es_p1 y el tipo de caso inferido de todos los tickets (sin confirmar)."""
    escalados = {
        f[0] for f in conexion.execute(
            "SELECT DISTINCT ticket_id FROM ticket_evento WHERE tipo = ?", (ev.ESCALAMIENTO,)
        )
    }
    filas = conexion.execute("SELECT id_glpi, prioridad_nivel, tipo_caso_origen FROM ticket").fetchall()
    for fila in filas:
        es_p1 = derivados.es_p1(fila["prioridad_nivel"], prioridad_p1)
        conexion.execute("UPDATE ticket SET es_p1 = ? WHERE id_glpi = ?", (int(es_p1), fila["id_glpi"]))
        if fila["tipo_caso_origen"] != "MANUAL":
            conexion.execute(
                "UPDATE ticket SET tipo_caso = ? WHERE id_glpi = ?",
                (derivados.inferir_tipo_caso(es_p1, fila["id_glpi"] in escalados), fila["id_glpi"]),
            )


# --- KPIs ---

def listar_kpis(conexion: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexion.execute("SELECT * FROM kpi_definicion ORDER BY orden").fetchall()


def actualizar_kpi(conexion: sqlite3.Connection, sesion: Sesion, codigo: str, cambios: dict) -> None:
    """Umbrales, meta, visibilidad, orden y marca de crítico. Los predefinidos no se borran."""
    seguridad.exigir_coordinador(sesion)
    fila = conexion.execute("SELECT * FROM kpi_definicion WHERE codigo = ?", (codigo,)).fetchone()
    if fila is None:
        raise ErrorValidacion(f"No existe el KPI «{codigo}».")
    desconocidos = set(cambios) - set(CAMPOS_KPI_EDITABLES)
    if desconocidos:
        raise ErrorValidacion(f"No se puede modificar: {', '.join(sorted(desconocidos))}.")
    final = {campo: cambios.get(campo, fila[campo]) for campo in CAMPOS_KPI_EDITABLES}
    for campo in ("visible_dashboard", "critico"):
        final[campo] = int(bool(final[campo]))
    final["orden"] = int(final["orden"])
    verde, amarillo = final["umbral_verde"], final["umbral_amarillo"]
    if verde is not None and amarillo is not None:
        if fila["direccion"] == MAYOR_MEJOR and amarillo > verde:
            raise ErrorValidacion("Si mayor es mejor, el umbral amarillo no puede superar al verde.")
        if fila["direccion"] == MENOR_MEJOR and amarillo < verde:
            raise ErrorValidacion("Si menor es mejor, el umbral amarillo no puede ser menor que el verde.")
    if amarillo is not None and verde is None:
        raise ErrorValidacion("Defina el umbral verde antes que el amarillo.")
    modificados = {c: v for c, v in final.items() if v != fila[c]}
    if not modificados:
        return
    with conexion:
        asignaciones = ", ".join(f"{c} = ?" for c in modificados)  # nombres de CAMPOS_KPI_EDITABLES
        conexion.execute(
            f"UPDATE kpi_definicion SET {asignaciones} WHERE codigo = ?", (*modificados.values(), codigo)
        )
        for campo, valor in modificados.items():
            historial.registrar(
                conexion, entidad="kpi_definicion", entidad_id=codigo, accion="MODIFICAR",
                usuario_id=sesion.usuario_id, campo=campo, valor_anterior=fila[campo], valor_nuevo=valor,
            )


# --- KPIs creados por el usuario (KPI-00) ---

CAMPOS_KPI_PERSONALIZADO = (
    "nombre", "descripcion", "tipo_calculo", "filtro_numerador_json", "filtro_denominador_json",
    "campo_tiempo", "direccion", "umbral_verde", "umbral_amarillo", "meta", "visible_dashboard", "critico",
)
PREFIJO_PERSONALIZADO = "KPI-U"


def definicion_kpi(datos: dict, codigo: str = "KPI-NUEVO") -> dict:
    """Definición completa y validada a partir de lo que llena el editor.

    `datos` trae las condiciones como listas en «numerador» y «denominador».
    Sirve para guardar y para la vista previa sin guardar.
    """
    nombre = " ".join((datos.get("nombre") or "").split())
    if not nombre:
        raise ErrorValidacion("Escriba el nombre del KPI.")
    tipo = datos.get("tipo_calculo")
    if tipo not in TIPOS_CALCULO:
        raise ErrorValidacion("Elija el tipo de cálculo.")
    campo_tiempo = datos.get("campo_tiempo") if tipo in TIPOS_TIEMPO else None
    if tipo in TIPOS_TIEMPO and campo_tiempo not in CAMPOS_TIEMPO:
        raise ErrorValidacion("Elija el campo de tiempo.")
    direccion = datos.get("direccion") or "INFORMATIVO"
    if direccion not in ("MAYOR_MEJOR", "MENOR_MEJOR", "INFORMATIVO"):
        raise ErrorValidacion("Dirección del semáforo inválida.")
    verde, amarillo = datos.get("umbral_verde"), datos.get("umbral_amarillo")
    if amarillo is not None and verde is None:
        raise ErrorValidacion("Defina el umbral verde antes que el amarillo.")
    if verde is not None and amarillo is not None:
        if direccion == MAYOR_MEJOR and amarillo > verde:
            raise ErrorValidacion("Si mayor es mejor, el umbral amarillo no puede superar al verde.")
        if direccion == MENOR_MEJOR and amarillo < verde:
            raise ErrorValidacion("Si menor es mejor, el umbral amarillo no puede ser menor que el verde.")
    return {
        "codigo": codigo, "nombre": nombre, "descripcion": (datos.get("descripcion") or "").strip(),
        "tipo_calculo": tipo, "calculo_especial": None,
        "filtro_numerador_json": condiciones.a_texto(datos.get("numerador") or []),
        "filtro_denominador_json": condiciones.a_texto(datos.get("denominador") or []) if tipo == "PORCENTAJE" else None,
        "campo_tiempo": campo_tiempo, "unidad": UNIDAD_POR_TIPO[tipo], "direccion": direccion,
        "umbral_verde": verde, "umbral_amarillo": amarillo, "meta": datos.get("meta"),
        "aproximado": int(tipo in TIPOS_TIEMPO), "critico": int(bool(datos.get("critico"))),
        "visible_dashboard": int(bool(datos.get("visible_dashboard", True))), "predefinido": 0,
    }


def guardar_kpi_personalizado(
    conexion: sqlite3.Connection, sesion: Sesion, datos: dict, codigo: str | None = None
) -> str:
    """Crea (sin código) o modifica un KPI creado por el usuario. Devuelve su código."""
    seguridad.exigir_coordinador(sesion)
    if codigo is not None:
        fila = conexion.execute("SELECT * FROM kpi_definicion WHERE codigo = ?", (codigo,)).fetchone()
        if fila is None:
            raise ErrorValidacion(f"No existe el KPI «{codigo}».")
        if fila["predefinido"]:
            raise ErrorValidacion("Los KPIs predefinidos solo permiten cambiar umbrales, visibilidad y orden.")
    else:
        numeros = [
            int(f[0][len(PREFIJO_PERSONALIZADO):]) for f in conexion.execute(
                "SELECT codigo FROM kpi_definicion WHERE codigo LIKE ?", (PREFIJO_PERSONALIZADO + "%",)
            )
        ]
        codigo = f"{PREFIJO_PERSONALIZADO}{max(numeros, default=0) + 1:02d}"
    definicion = definicion_kpi(datos, codigo)
    with conexion:
        if fila_existe := conexion.execute("SELECT * FROM kpi_definicion WHERE codigo = ?", (codigo,)).fetchone():
            for campo in CAMPOS_KPI_PERSONALIZADO + ("unidad", "aproximado"):
                if fila_existe[campo] != definicion[campo]:
                    conexion.execute(f"UPDATE kpi_definicion SET {campo} = ? WHERE codigo = ?",
                                     (definicion[campo], codigo))
                    historial.registrar(conexion, entidad="kpi_definicion", entidad_id=codigo, accion="MODIFICAR",
                                        usuario_id=sesion.usuario_id, campo=campo,
                                        valor_anterior=fila_existe[campo], valor_nuevo=definicion[campo])
        else:
            orden = conexion.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM kpi_definicion").fetchone()[0]
            columnas = [c for c in definicion if c != "codigo"]
            conexion.execute(
                f"INSERT INTO kpi_definicion (codigo, orden, {', '.join(columnas)}) "
                f"VALUES (?, ?, {', '.join('?' * len(columnas))})",
                (codigo, orden, *(definicion[c] for c in columnas)),
            )
            historial.registrar(conexion, entidad="kpi_definicion", entidad_id=codigo, accion="CREAR",
                                usuario_id=sesion.usuario_id, valor_nuevo=definicion["nombre"])
    return codigo


def eliminar_kpi_personalizado(conexion: sqlite3.Connection, sesion: Sesion, codigo: str) -> None:
    seguridad.exigir_coordinador(sesion)
    fila = conexion.execute("SELECT * FROM kpi_definicion WHERE codigo = ?", (codigo,)).fetchone()
    if fila is None:
        raise ErrorValidacion(f"No existe el KPI «{codigo}».")
    if fila["predefinido"]:
        raise ErrorValidacion("Los KPIs predefinidos no se pueden eliminar; puede ocultarlos del dashboard.")
    with conexion:
        conexion.execute("DELETE FROM kpi_definicion WHERE codigo = ?", (codigo,))
        historial.registrar(conexion, entidad="kpi_definicion", entidad_id=codigo, accion="ELIMINAR",
                            usuario_id=sesion.usuario_id, valor_anterior=fila["nombre"])


# --- Técnicos ---

def listar_tecnicos(conexion: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexion.execute("SELECT * FROM tecnico ORDER BY nombre_mostrar").fetchall()


def actualizar_tecnico(
    conexion: sqlite3.Connection, sesion: Sesion, tecnico_id: int, *,
    nombre_mostrar: str, turno: str | None, activo: bool, incluir_en_ranking: bool,
) -> None:
    seguridad.exigir_coordinador(sesion)
    fila = conexion.execute("SELECT * FROM tecnico WHERE id = ?", (tecnico_id,)).fetchone()
    if fila is None:
        raise ErrorValidacion("El técnico no existe.")
    nombre_mostrar = " ".join(nombre_mostrar.split())
    if not nombre_mostrar:
        raise ErrorValidacion("Escriba el nombre que se mostrará del técnico.")
    if turno is not None and turno not in TURNOS_TECNICO:
        raise ErrorValidacion(f"El turno debe ser uno de: {', '.join(TURNOS_TECNICO)}.")
    nuevos = {
        "nombre_mostrar": nombre_mostrar, "turno": turno,
        "activo": int(activo), "incluir_en_ranking": int(incluir_en_ranking),
    }
    modificados = {c: v for c, v in nuevos.items() if v != fila[c]}
    if not modificados:
        return
    with conexion:
        asignaciones = ", ".join(f"{c} = ?" for c in modificados)  # nombres fijos de `nuevos`
        conexion.execute(f"UPDATE tecnico SET {asignaciones} WHERE id = ?", (*modificados.values(), tecnico_id))
        for campo, valor in modificados.items():
            historial.registrar(
                conexion, entidad="tecnico", entidad_id=tecnico_id, accion="MODIFICAR",
                usuario_id=sesion.usuario_id, campo=campo, valor_anterior=fila[campo], valor_nuevo=valor,
            )


# --- Festivos ---

def listar_festivos(conexion: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexion.execute("SELECT fecha, descripcion FROM festivo ORDER BY fecha").fetchall()


def agregar_festivos(conexion: sqlite3.Connection, sesion: Sesion, festivos: list[tuple[date, str]]) -> int:
    """Agrega los que no existan. Devuelve cuántos se agregaron."""
    seguridad.exigir_coordinador(sesion)
    agregados = 0
    with conexion:
        for dia, descripcion in festivos:
            descripcion = descripcion.strip() or "Festivo"
            cursor = conexion.execute(
                "INSERT OR IGNORE INTO festivo (fecha, descripcion) VALUES (?, ?)", (dia.isoformat(), descripcion)
            )
            if cursor.rowcount:
                agregados += 1
                historial.registrar(
                    conexion, entidad="festivo", entidad_id=dia.isoformat(), accion="CREAR",
                    usuario_id=sesion.usuario_id, valor_nuevo=descripcion,
                )
    return agregados


def proponer_festivos(anio: int) -> list[tuple[date, str]]:
    """Festivos de ley de Colombia del año, para que el coordinador los confirme."""
    return calendario.festivos_colombia(anio)


def eliminar_festivo(conexion: sqlite3.Connection, sesion: Sesion, dia: date) -> None:
    seguridad.exigir_coordinador(sesion)
    fila = conexion.execute("SELECT descripcion FROM festivo WHERE fecha = ?", (dia.isoformat(),)).fetchone()
    if fila is None:
        return
    with conexion:
        conexion.execute("DELETE FROM festivo WHERE fecha = ?", (dia.isoformat(),))
        historial.registrar(
            conexion, entidad="festivo", entidad_id=dia.isoformat(), accion="ELIMINAR",
            usuario_id=sesion.usuario_id, valor_anterior=fila[0],
        )


# --- Franjas de turno (config.ini) ---

def guardar_franjas(
    conexion: sqlite3.Connection, sesion: Sesion, archivo_config: Path, franjas: dict[str, str]
) -> tuple[Franja, ...]:
    """Valida y escribe la sección [turnos] de config.ini, y recalcula el turno de
    apertura de los tickets existentes. Devuelve las franjas nuevas."""
    seguridad.exigir_coordinador(sesion)
    nuevas = tuple(interpretar_franja(turno.strip(), texto) for turno, texto in franjas.items())
    validar_franjas(nuevas)
    anteriores = _leer_seccion_turnos(archivo_config)
    _escribir_seccion_turnos(archivo_config, {f.turno: franjas[f.turno] for f in nuevas})
    with conexion:
        recalcular_turnos(conexion, nuevas)
        historial.registrar(
            conexion, entidad="config.ini", entidad_id="turnos", accion="MODIFICAR",
            usuario_id=sesion.usuario_id,
            valor_anterior="; ".join(f"{k} = {v}" for k, v in anteriores.items()),
            valor_nuevo="; ".join(f"{k} = {v.strip()}" for k, v in franjas.items()),
        )
    return nuevas


def recalcular_turnos(conexion: sqlite3.Connection, franjas: tuple[Franja, ...]) -> None:
    """Turno de apertura de todos los tickets con las franjas dadas (sin confirmar)."""
    filas = conexion.execute("SELECT id_glpi, fecha_apertura FROM ticket").fetchall()
    conexion.executemany(
        "UPDATE ticket SET turno_apertura = ? WHERE id_glpi = ?",
        [
            (derivados.turno_apertura(datetime.fromisoformat(f["fecha_apertura"]), franjas), f["id_glpi"])
            for f in filas
        ],
    )


def _leer_seccion_turnos(archivo: Path) -> dict[str, str]:
    lector = configparser.ConfigParser(interpolation=None)
    lector.optionxform = str
    lector.read(archivo, encoding="utf-8-sig")
    return dict(lector.items("turnos")) if lector.has_section("turnos") else {}


def _escribir_seccion_turnos(archivo: Path, franjas: dict[str, str]) -> None:
    """Reemplaza solo las líneas de la sección [turnos]; conserva comentarios y el resto."""
    try:
        lineas = archivo.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ErrorConfiguracion(f"No se pudo leer {NOMBRE_ARCHIVO}.", detalle=repr(error)) from error
    salida, en_turnos, escritas = [], False, False
    for linea in lineas:
        limpia = linea.strip()
        if limpia.startswith("[") and limpia.endswith("]"):
            if en_turnos and not escritas:
                salida.extend(f"{t} = {v.strip()}" for t, v in franjas.items())
                salida.append("")
                escritas = True
            en_turnos = limpia == "[turnos]"
            salida.append(linea)
            continue
        if en_turnos and limpia and not limpia.startswith((";", "#")):
            continue  # franja anterior: se reemplaza
        salida.append(linea)
    if en_turnos and not escritas:
        salida.extend(f"{t} = {v.strip()}" for t, v in franjas.items())
    elif not escritas:
        salida.extend(["", "[turnos]", *(f"{t} = {v.strip()}" for t, v in franjas.items())])
    try:
        archivo.write_text("\n".join(salida) + "\n", encoding="utf-8")
    except OSError as error:
        raise ErrorConfiguracion(
            f"No se pudo guardar {NOMBRE_ARCHIVO}. Verifique los permisos de escritura.", detalle=repr(error)
        ) from error


def parametro_texto(conexion: sqlite3.Connection, clave: str) -> str:
    """Valor del parámetro como texto para mostrar ("" si está vacío)."""
    return parametros.valor(conexion, clave) or ""
