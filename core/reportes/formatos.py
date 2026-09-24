"""Escritura de reportes en Excel (openpyxl) y CSV (pandas).

Un reporte es un encabezado (título, período, filtros, fecha, usuario) y una o
más hojas con tablas, gráficos como imagen y notas. El CSV contiene la tabla
principal del reporte, con «;» y UTF-8 con BOM para que Excel lo abra bien.
"""

import io
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ImagenExcel
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from core.analisis import semaforo
from core.errores import ErrorAplicacion

AZUL_MARINO = "1F3A5F"
RELLENO_SEMAFORO = {
    semaforo.VERDE: "C8E6C9",
    semaforo.AMARILLO: "FFF3C4",
    semaforo.ROJO: "FFCDD2",
}
ANCHO_MAXIMO_COLUMNA = 60


@dataclass
class Tabla:
    titulo: str
    datos: pd.DataFrame
    # Columna cuyo texto es un semáforo (por ejemplo «✖ Rojo») → se colorea la celda
    columna_semaforo: str | None = None


@dataclass
class Hoja:
    nombre: str
    tablas: list[Tabla] = field(default_factory=list)
    imagenes: list[bytes] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)


@dataclass
class Reporte:
    titulo: str
    encabezado: dict[str, str]  # Período, Filtros, Generado, Usuario
    hojas: list[Hoja]


def _color_de(texto: str) -> str | None:
    for color, nombre in semaforo.TEXTOS.items():
        if isinstance(texto, str) and texto.endswith(nombre) and color in RELLENO_SEMAFORO:
            return RELLENO_SEMAFORO[color]
    return None


def _escribir_tabla(hoja_excel, fila: int, tabla: Tabla) -> int:
    hoja_excel.cell(row=fila, column=1, value=tabla.titulo).font = Font(bold=True, size=12, color=AZUL_MARINO)
    fila += 1
    columnas = list(tabla.datos.columns)
    for indice, nombre in enumerate(columnas, start=1):
        celda = hoja_excel.cell(row=fila, column=indice, value=nombre)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor=AZUL_MARINO)
        celda.alignment = Alignment(wrap_text=True, vertical="center")
    for registro in tabla.datos.itertuples(index=False):
        fila += 1
        for indice, valor in enumerate(registro, start=1):
            if valor is not None and not isinstance(valor, str) and pd.isna(valor):
                valor = None  # NaN de pandas → celda vacía
            celda = hoja_excel.cell(row=fila, column=indice, value=valor)
            if columnas[indice - 1] == tabla.columna_semaforo and (color := _color_de(valor)):
                celda.fill = PatternFill("solid", fgColor=color)
    for indice, nombre in enumerate(columnas, start=1):
        largo = max([len(str(nombre))] + [len(str(v)) for v in tabla.datos.iloc[:, indice - 1]])
        letra = get_column_letter(indice)
        actual = hoja_excel.column_dimensions[letra].width or 0
        hoja_excel.column_dimensions[letra].width = max(actual, min(largo + 2, ANCHO_MAXIMO_COLUMNA))
    return fila + 2


def escribir_excel(reporte: Reporte, ruta: Path) -> Path:
    libro = Workbook()
    libro.remove(libro.active)
    for hoja in reporte.hojas:
        hoja_excel = libro.create_sheet(hoja.nombre[:31])
        hoja_excel.cell(row=1, column=1, value=reporte.titulo).font = Font(bold=True, size=14, color=AZUL_MARINO)
        fila = 2
        for clave, valor in reporte.encabezado.items():
            hoja_excel.cell(row=fila, column=1, value=clave).font = Font(bold=True)
            hoja_excel.cell(row=fila, column=2, value=valor)
            fila += 1
        fila += 1
        for tabla in hoja.tablas:
            fila = _escribir_tabla(hoja_excel, fila, tabla)
        for nota in hoja.notas:
            hoja_excel.cell(row=fila, column=1, value=nota).font = Font(italic=True, color="555555")
            fila += 1
        fila += 1
        for png in hoja.imagenes:
            imagen = ImagenExcel(io.BytesIO(png))
            hoja_excel.add_image(imagen, f"A{fila}")
            fila += int(imagen.height / 20) + 2
    return _guardar(lambda: libro.save(ruta), ruta)


def escribir_csv(tabla: Tabla, ruta: Path) -> Path:
    return _guardar(lambda: tabla.datos.to_csv(ruta, sep=";", index=False, encoding="utf-8-sig"), ruta)


def _guardar(escribir, ruta: Path) -> Path:
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        escribir()
    except OSError as error:
        raise ErrorAplicacion(
            f"No se pudo guardar «{ruta.name}». Verifique que no esté abierto en Excel "
            "y que tenga permisos de escritura.",
            detalle=repr(error),
        ) from error
    return ruta


def anonimizar(datos: pd.DataFrame, columnas: tuple[str, ...]) -> pd.DataFrame:
    """Reemplaza nombres de personas por «Persona 001», «Persona 002»… (IMP-05, RNF-08).

    El mismo nombre recibe siempre el mismo reemplazo dentro de la exportación.
    """
    copia = datos.copy()
    for columna in columnas:
        if columna not in copia:
            continue
        codigos: dict[str, str] = {}
        def reemplazar(valor):
            if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor == "":
                return valor
            return codigos.setdefault(valor, f"Persona {len(codigos) + 1:03d}")
        copia[columna] = copia[columna].map(reemplazar)
    return copia
