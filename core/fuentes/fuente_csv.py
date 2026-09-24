"""Lectura de la exportación CSV de GLPI con autodetección (IMP-00, IMP-01, IMP-02).

Detecta la codificación, el separador, los encabezados (descartando la columna
vacía que deja el «;» final) y el formato de fecha. Lee en bloques (`chunksize`).
Todas las celdas se entregan como texto, sin interpretar.
"""

import csv
import hashlib
import io
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.errores import ErrorAplicacion, ErrorValidacion
from core.fuentes.base import COLUMNA_FILA, FuenteDatos

SEPARADORES = (";", ",", "\t", "|")
MUESTRA_FILAS = 200
PROPORCION_MINIMA_FECHAS = 0.8

# Día antes que mes: en Colombia un 06-04-2026 es 6 de abril
FORMATOS_FECHA = (
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m-%d-%Y %H:%M",
    "%m/%d/%Y %H:%M",
)
_PARECE_FECHA = re.compile(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4} \d{1,2}:\d{2}(:\d{2})?$")


@dataclass(frozen=True)
class FormatoCSV:
    codificacion: str
    separador: str
    encabezados: tuple[str, ...]
    formato_fecha: str | None = None
    columnas_fecha: tuple[str, ...] = ()
    # Todas las fechas de la muestra admiten día/mes y mes/día: el usuario debe confirmar
    fecha_ambigua: bool = False


# --- Detección ---

def detectar_codificacion(datos: bytes) -> str:
    if datos.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        datos.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        datos.decode("cp1252")
        return "cp1252"
    except UnicodeDecodeError:
        return "latin-1"


def detectar_separador(linea_encabezados: str) -> str:
    """El separador más frecuente fuera de comillas en la línea de encabezados."""
    sin_comillas = re.sub(r'"[^"]*"', "", linea_encabezados)
    conteos = {sep: sin_comillas.count(sep) for sep in SEPARADORES}
    separador = max(conteos, key=conteos.get)
    if conteos[separador] == 0:
        raise ErrorValidacion(
            "No se reconoció el separador de columnas del archivo. "
            "Verifique que sea una exportación CSV de GLPI."
        )
    return separador


def leer_encabezados(texto: str, separador: str) -> tuple[str, ...]:
    """Encabezados sin la columna vacía final ni espacios sobrantes."""
    try:
        primera = next(csv.reader(io.StringIO(texto, newline=""), delimiter=separador))
    except StopIteration:
        raise ErrorValidacion("El archivo está vacío.") from None
    encabezados = [e.strip() for e in primera]
    while encabezados and not encabezados[-1]:
        encabezados.pop()
    if not encabezados:
        raise ErrorValidacion("El archivo no tiene encabezados.")
    if "" in encabezados:
        raise ErrorValidacion(
            f"La columna {encabezados.index('') + 1} del archivo no tiene encabezado."
        )
    repetidos = sorted({e for e in encabezados if encabezados.count(e) > 1})
    if repetidos:
        raise ErrorValidacion(
            f"El archivo tiene encabezados repetidos: {', '.join(repetidos)}."
        )
    return tuple(encabezados)


def detectar_formato_fecha(
    muestra: pd.DataFrame,
) -> tuple[str | None, tuple[str, ...], bool]:
    """Columnas con fechas, el formato que mejor las interpreta y si es ambiguo."""
    columnas = []
    valores: list[str] = []
    for columna in muestra.columns:
        if columna == COLUMNA_FILA:
            continue
        no_vacios = [v.strip() for v in muestra[columna] if v and v.strip()]
        if not no_vacios:
            continue
        parecidos = [v for v in no_vacios if _PARECE_FECHA.match(v)]
        if len(parecidos) / len(no_vacios) >= PROPORCION_MINIMA_FECHAS:
            columnas.append(columna)
            valores.extend(parecidos)
    if not valores:
        return None, (), False
    aciertos = {formato: _cuantas_interpreta(valores, formato) for formato in FORMATOS_FECHA}
    mejor = max(FORMATOS_FECHA, key=lambda f: aciertos[f])  # empate: el primero (día antes que mes)
    if aciertos[mejor] == 0:
        return None, tuple(columnas), False
    alternativa = _invertir_dia_mes(mejor)
    ambigua = alternativa is not None and aciertos[alternativa] == aciertos[mejor]
    return mejor, tuple(columnas), ambigua


def _cuantas_interpreta(valores: list[str], formato: str) -> int:
    total = 0
    for valor in valores:
        try:
            datetime.strptime(valor, formato)
            total += 1
        except ValueError:
            pass
    return total


def _invertir_dia_mes(formato: str) -> str | None:
    for dia_mes, mes_dia in (("%d-%m", "%m-%d"), ("%d/%m", "%m/%d")):
        if formato.startswith(dia_mes):
            return formato.replace(dia_mes, mes_dia, 1)
        if formato.startswith(mes_dia):
            return formato.replace(mes_dia, dia_mes, 1)
    return None


# --- Fuente ---

class FuenteCSV(FuenteDatos):
    """Exportación CSV de tickets de GLPI."""

    def __init__(self, ruta: Path, formato: FormatoCSV | None = None, tamano_bloque: int = 5000):
        self.ruta = ruta
        self.tamano_bloque = tamano_bloque
        try:
            self._datos = ruta.read_bytes()
        except OSError as error:
            raise ErrorAplicacion(
                f"No se pudo leer el archivo «{ruta.name}». Verifique que exista y "
                "que no esté abierto en otro programa.",
                detalle=repr(error),
            ) from error
        if not self._datos.strip():
            raise ErrorValidacion("El archivo está vacío.")
        self.hash = hashlib.sha256(self._datos).hexdigest()
        self.formato = formato or self.detectar_formato()

    def detectar_formato(self) -> FormatoCSV:
        """Propone codificación, separador, encabezados y formato de fecha."""
        codificacion = detectar_codificacion(self._datos)
        texto = self._datos.decode(codificacion)
        separador = detectar_separador(texto.splitlines()[0])
        encabezados = leer_encabezados(texto, separador)
        base = FormatoCSV(codificacion, separador, encabezados)
        muestra = self._leer(base, texto, filas=MUESTRA_FILAS)
        formato_fecha, columnas, ambigua = detectar_formato_fecha(muestra)
        return FormatoCSV(codificacion, separador, encabezados, formato_fecha, columnas, ambigua)

    def con_ajustes(self, codificacion: str, separador: str, formato_fecha: str | None) -> "FuenteCSV":
        """La misma fuente con la codificación, el separador o el formato de fecha que
        eligió el usuario; los encabezados se vuelven a leer con esos ajustes."""
        try:
            texto = self._datos.decode(codificacion)
        except (UnicodeDecodeError, LookupError) as error:
            raise ErrorValidacion(
                f"El archivo no se puede leer con la codificación «{codificacion}».", detalle=repr(error)
            ) from error
        encabezados = leer_encabezados(texto, separador)
        formato = FormatoCSV(
            codificacion, separador, encabezados, formato_fecha,
            self.formato.columnas_fecha, self.formato.fecha_ambigua,
        )
        return FuenteCSV(self.ruta, formato, self.tamano_bloque)

    def muestra(self, filas: int = MUESTRA_FILAS) -> pd.DataFrame:
        return self._leer(self.formato, self._texto(), filas=filas)

    def obtener_tickets(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> Iterator[pd.DataFrame]:
        """Todas las filas en bloques; el CSV ya viene filtrado por quien lo exportó."""
        texto = self._texto()
        encabezados = leer_encabezados(texto, self.formato.separador)
        if encabezados != self.formato.encabezados:
            raise ErrorValidacion(
                "Los encabezados del archivo no coinciden con el formato indicado."
            )
        yield from self._bloques(self.formato, texto)

    def obtener_seguimientos(self, ids: Iterable[int]) -> Iterator[pd.DataFrame]:
        raise ErrorAplicacion(
            "La importación de seguimientos se habilita en la Fase 3."
        )

    # --- Interno ---

    def _texto(self) -> str:
        try:
            return self._datos.decode(self.formato.codificacion)
        except (UnicodeDecodeError, LookupError) as error:
            raise ErrorValidacion(
                f"El archivo no se puede leer con la codificación «{self.formato.codificacion}». "
                "Pruebe con otra codificación en el perfil de importación.",
                detalle=repr(error),
            ) from error

    def _lector(self, formato: FormatoCSV, texto: str, **opciones):
        cantidad = len(formato.encabezados)
        try:
            return pd.read_csv(
                io.StringIO(texto, newline=""),
                sep=formato.separador,
                header=None,
                skiprows=1,
                names=list(range(cantidad)),
                usecols=list(range(cantidad)),
                dtype=str,
                keep_default_na=False,
                quotechar='"',
                skip_blank_lines=True,
                index_col=False,
                **opciones,
            )
        except (pd.errors.ParserError, ValueError) as error:
            raise ErrorValidacion(
                "El archivo tiene un formato CSV dañado (comillas sin cerrar o "
                "filas mal formadas).",
                detalle=repr(error),
            ) from error

    def _preparar(self, bloque: pd.DataFrame, formato: FormatoCSV, primera_fila: int) -> pd.DataFrame:
        bloque.columns = list(formato.encabezados)
        # Filas con menos columnas que los encabezados: las celdas faltantes quedan vacías
        bloque = bloque.fillna("")
        # Número de registro como en una hoja de cálculo: la fila 1 son los encabezados
        bloque.insert(0, COLUMNA_FILA, range(primera_fila, primera_fila + len(bloque)))
        return bloque.reset_index(drop=True)

    def _leer(self, formato: FormatoCSV, texto: str, filas: int) -> pd.DataFrame:
        return self._preparar(self._lector(formato, texto, nrows=filas), formato, 2)

    def _bloques(self, formato: FormatoCSV, texto: str) -> Iterator[pd.DataFrame]:
        siguiente = 2
        lector = self._lector(formato, texto, chunksize=self.tamano_bloque)
        try:
            for bloque in lector:
                yield self._preparar(bloque, formato, siguiente)
                siguiente += len(bloque)
        except pd.errors.ParserError as error:
            raise ErrorValidacion(
                f"El archivo tiene un formato CSV dañado cerca de la fila {siguiente}.",
                detalle=repr(error),
            ) from error
