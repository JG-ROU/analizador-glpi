"""Validación de filas antes de guardar (IMP-02, CA-03).

Cada fila queda VALIDA (verde), ADVERTENCIA (amarillo; se carga) o ERROR (rojo;
no se carga), con sus motivos en español. De paso se interpretan los valores:
ID numérico, fechas, estado y prioridad normalizados y lista de técnicos.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.errores import ErrorAplicacion
from core.fuentes.base import COLUMNA_FILA
from core.importacion.mapeo import CAMPOS_TICKET, PerfilImportacion

VALIDA = "VALIDA"
ADVERTENCIA = "ADVERTENCIA"
ERROR = "ERROR"

# Separadores de miles que usa GLPI en el ID: espacio, espacio duro y espacio fino
_SEPARADORES_MILES = re.compile(r"[   ]")
_TRADUCCION_FORMATO = {"%d": "DD", "%m": "MM", "%Y": "AAAA", "%H": "HH", "%M": "MM", "%S": "SS"}

COLUMNAS_RESULTADO = (
    COLUMNA_FILA,
    "id_glpi",
    "titulo",
    "entidad",
    "estado",
    "estado_codigo",
    "autor",
    "tecnicos",
    "fecha_apertura",
    "ultima_actualizacion",
    "prioridad",
    "prioridad_nivel",
    "ubicacion",
    "resultado",
    "motivos",
)


# --- Interpretación de valores ---

def normalizar_id(texto: str) -> int | None:
    """«346 649» → 346649. None si queda vacío o no es numérico."""
    limpio = _SEPARADORES_MILES.sub("", texto.strip())
    return int(limpio) if limpio.isdigit() else None


def leer_fecha(texto: str, formato: str) -> datetime | None:
    try:
        return datetime.strptime(texto.strip(), formato)
    except ValueError:
        return None


def separar_tecnicos(texto: str, separador: str) -> tuple[str, ...]:
    """Nombres no vacíos, sin repetir y en el orden del archivo."""
    partes = texto.replace("\r\n", "\n").split(separador.replace("\r\n", "\n"))
    nombres = []
    for parte in partes:
        nombre = " ".join(parte.split())
        if nombre and nombre not in nombres:
            nombres.append(nombre)
    return tuple(nombres)


def formato_legible(formato: str) -> str:
    """%d-%m-%Y %H:%M → DD-MM-AAAA HH:MM."""
    for codigo, texto in _TRADUCCION_FORMATO.items():
        formato = formato.replace(codigo, texto)
    return formato


# --- Validación ---

class ValidadorTickets:
    """Valida bloques sucesivos del mismo archivo; recuerda los ID ya vistos."""

    def __init__(self, perfil: PerfilImportacion):
        self.perfil = perfil
        self._ids_vistos: dict[int, int] = {}  # id → fila donde apareció primero

    def validar_bloque(self, bloque: pd.DataFrame) -> pd.DataFrame:
        columnas = self.perfil.mapeo.columnas
        vacia = pd.Series([""] * len(bloque), index=bloque.index, dtype=object)
        valores = {
            campo.nombre: bloque[columnas[campo.nombre]] if columnas.get(campo.nombre) else vacia
            for campo in CAMPOS_TICKET
        }
        filas = [
            self._validar_fila(numero, {nombre: serie.iloc[i] for nombre, serie in valores.items()})
            for i, numero in enumerate(bloque[COLUMNA_FILA])
        ]
        return pd.DataFrame(filas, columns=list(COLUMNAS_RESULTADO))

    def _validar_fila(self, numero: int, crudo: dict[str, str]) -> dict:
        errores: list[str] = []
        advertencias: list[str] = []
        mapeo = self.perfil.mapeo
        formato = self.perfil.formato_fecha

        id_glpi = None
        texto_id = crudo["id_glpi"].strip()
        if not texto_id:
            errores.append("ID vacío")
        else:
            id_glpi = normalizar_id(texto_id)
            if id_glpi is None:
                errores.append(f"El ID «{texto_id}» no es numérico")
            elif id_glpi in self._ids_vistos:
                errores.append(f"ID repetido: ya aparece en la fila {self._ids_vistos[id_glpi]}")
            else:
                self._ids_vistos[id_glpi] = numero

        titulo = " ".join(crudo["titulo"].split())
        if not titulo:
            errores.append("Título vacío")

        fechas = {}
        for campo, etiqueta in (
            ("fecha_apertura", "Fecha de apertura"),
            ("ultima_actualizacion", "Última actualización"),
        ):
            texto = crudo[campo].strip()
            fecha = leer_fecha(texto, formato) if texto else None
            if not texto:
                errores.append(f"{etiqueta} vacía")
            elif fecha is None:
                errores.append(
                    f"{etiqueta} inválida: «{texto}» (formato esperado {formato_legible(formato)})"
                )
            fechas[campo] = fecha

        estado = crudo["estado"].strip()
        estado_codigo = mapeo.codigo_estado(estado) if estado else None
        if not estado:
            errores.append("Estado vacío")
        elif estado_codigo is None:
            errores.append(
                f"Estado sin mapear: «{estado}». Asócielo a un estado en el perfil de importación"
            )

        prioridad = crudo["prioridad"].strip()
        prioridad_nivel = mapeo.nivel_prioridad(prioridad) if prioridad else None
        if not prioridad:
            errores.append("Prioridad vacía")
        elif prioridad_nivel is None:
            errores.append(
                f"Prioridad sin mapear: «{prioridad}». Asóciela a un nivel en el perfil de importación"
            )

        tecnicos = separar_tecnicos(crudo["tecnico"], self.perfil.separador_multivalor)
        if not tecnicos:
            advertencias.append("Sin técnico asignado")
        apertura, actualizacion = fechas["fecha_apertura"], fechas["ultima_actualizacion"]
        if apertura and actualizacion and actualizacion < apertura:
            advertencias.append("La última actualización es anterior a la fecha de apertura")

        if errores:
            resultado, motivos = ERROR, errores + advertencias
        elif advertencias:
            resultado, motivos = ADVERTENCIA, advertencias
        else:
            resultado, motivos = VALIDA, []
        return {
            COLUMNA_FILA: numero,
            "id_glpi": id_glpi,
            "titulo": titulo,
            "entidad": " ".join(crudo["entidad"].split()) or None,
            "estado": estado,
            "estado_codigo": estado_codigo,
            "autor": " ".join(crudo["autor"].split()) or None,
            "tecnicos": tecnicos,
            "fecha_apertura": apertura,
            "ultima_actualizacion": actualizacion,
            "prioridad": prioridad,
            "prioridad_nivel": prioridad_nivel,
            "ubicacion": " ".join(crudo["ubicacion"].split()) or None,
            "resultado": resultado,
            "motivos": "; ".join(motivos),
        }


@dataclass
class ResultadoValidacion:
    filas: pd.DataFrame  # interpretadas, con resultado y motivos
    originales: pd.DataFrame  # tal como venían en el archivo, para exportar los errores

    @property
    def cargables(self) -> pd.DataFrame:
        """Filas válidas y con advertencia: las que se importan."""
        return self.filas[self.filas["resultado"] != ERROR]

    @property
    def con_error(self) -> pd.DataFrame:
        return self.filas[self.filas["resultado"] == ERROR]

    def conteo(self, resultado: str) -> int:
        return int((self.filas["resultado"] == resultado).sum())

    @property
    def filas_leidas(self) -> int:
        return len(self.filas)

    @property
    def rango_fechas(self) -> tuple[datetime | None, datetime | None]:
        """Primera y última fecha de apertura de las filas cargables."""
        fechas = self.cargables["fecha_apertura"].dropna()
        if fechas.empty:
            return None, None
        return fechas.min().to_pydatetime(), fechas.max().to_pydatetime()


def validar(bloques: Iterable[pd.DataFrame], perfil: PerfilImportacion) -> ResultadoValidacion:
    """Valida todos los bloques de un archivo."""
    validador = ValidadorTickets(perfil)
    interpretadas, originales = [], []
    for bloque in bloques:
        interpretadas.append(validador.validar_bloque(bloque))
        originales.append(bloque)
    if not interpretadas:
        vacio = pd.DataFrame(columns=list(COLUMNAS_RESULTADO))
        return ResultadoValidacion(vacio, pd.DataFrame(columns=[COLUMNA_FILA]))
    filas = pd.concat(interpretadas, ignore_index=True)
    filas["id_glpi"] = filas["id_glpi"].astype("Int64")
    filas["prioridad_nivel"] = filas["prioridad_nivel"].astype("Int64")
    return ResultadoValidacion(filas, pd.concat(originales, ignore_index=True))


def exportar_errores(resultado: ResultadoValidacion, ruta: Path) -> Path:
    """CSV con las filas con error tal como venían, más la fila y el motivo.

    Se escribe con «;» y UTF-8 con BOM para que Excel lo abra bien.
    """
    errores = resultado.con_error[[COLUMNA_FILA, "motivos"]]
    originales = resultado.originales.merge(errores, on=COLUMNA_FILA)
    salida = originales.rename(columns={COLUMNA_FILA: "Fila", "motivos": "Motivo del error"})
    columnas = ["Fila", "Motivo del error"] + [
        c for c in salida.columns if c not in ("Fila", "Motivo del error")
    ]
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        salida[columnas].to_csv(ruta, sep=";", index=False, encoding="utf-8-sig")
    except OSError as error:
        raise ErrorAplicacion(
            f"No se pudo guardar el archivo de errores en «{ruta}». "
            "Verifique que no esté abierto en Excel.",
            detalle=repr(error),
        ) from error
    return ruta
