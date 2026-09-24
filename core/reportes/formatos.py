"""Escritura de reportes en Excel (openpyxl), PDF (fpdf2) y CSV (pandas).

Un reporte es un encabezado (título, período, filtros, fecha, usuario) y una o
más hojas con tablas, gráficos como imagen y notas. El CSV contiene la tabla
principal del reporte, con «;» y UTF-8 con BOM para que Excel lo abra bien.
"""

import io
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
import pandas as pd
from fpdf import FPDF, FontFace, XPos, YPos
from openpyxl import Workbook
from PIL import Image as PilImage
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


RELLENO_SEMAFORO_RGB = {color: tuple(int(hexa[i:i + 2], 16) for i in (0, 2, 4))
                        for color, hexa in RELLENO_SEMAFORO.items()}
AZUL_MARINO_RGB = (31, 58, 95)
FUENTE_PDF = "DejaVu"
ANCHO_IMAGEN_MM = 170


def _texto_pdf(valor) -> str:
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    if isinstance(valor, float):
        return f"{round(valor, 2):g}"
    return str(valor)


class _Pdf(FPDF):
    """PDF apaisado con encabezado (título, período, filtros, fecha, usuario) y paginación."""

    def __init__(self, reporte: Reporte):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.reporte = reporte
        carpeta = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        self.add_font(FUENTE_PDF, "", str(carpeta / "DejaVuSans.ttf"))
        self.add_font(FUENTE_PDF, "B", str(carpeta / "DejaVuSans-Bold.ttf"))
        self.add_font(FUENTE_PDF, "I", str(carpeta / "DejaVuSans.ttf"))
        self.set_auto_page_break(True, margin=15)
        self.alias_nb_pages()
        self.set_title(reporte.titulo)
        self.set_creator("Analizador GLPI")

    def header(self) -> None:
        self.set_font(FUENTE_PDF, "B", 13)
        self.set_text_color(*AZUL_MARINO_RGB)
        self.cell(0, 8, self.reporte.titulo, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font(FUENTE_PDF, "", 8)
        self.set_text_color(80, 80, 80)
        self.multi_cell(0, 4.5, "   ·   ".join(f"{k}: {v}" for k, v in self.reporte.encabezado.items()),
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*AZUL_MARINO_RGB)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(FUENTE_PDF, "", 8)
        self.set_text_color(110, 110, 110)
        self.cell(0, 8, f"Página {self.page_no()} de {{nb}}", align="C")

    def tabla(self, tabla: Tabla) -> None:
        self.set_font(FUENTE_PDF, "B", 10)
        self.set_text_color(*AZUL_MARINO_RGB)
        self.cell(0, 7, tabla.titulo, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)
        columnas = [str(c) for c in tabla.datos.columns]
        self.set_font(FUENTE_PDF, "", 7 if len(columnas) > 8 else 8)
        encabezado = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL_MARINO_RGB)
        with self.table(headings_style=encabezado, line_height=4.2, text_align="LEFT",
                        borders_layout="HORIZONTAL_LINES") as tabla_pdf:
            fila = tabla_pdf.row()
            for columna in columnas:
                fila.cell(columna)
            indice_semaforo = columnas.index(tabla.columna_semaforo) if tabla.columna_semaforo in columnas else None
            for registro in tabla.datos.itertuples(index=False):
                fila = tabla_pdf.row()
                for posicion, valor in enumerate(registro):
                    texto = _texto_pdf(valor)
                    estilo = None
                    if posicion == indice_semaforo:
                        color = next((c for c, n in semaforo.TEXTOS.items() if texto.endswith(n)), None)
                        if color in RELLENO_SEMAFORO_RGB:
                            estilo = FontFace(fill_color=RELLENO_SEMAFORO_RGB[color])
                    fila.cell(texto, style=estilo)
        self.ln(3)

    def imagen(self, png: bytes) -> None:
        with PilImage.open(io.BytesIO(png)) as imagen:
            ancho, alto = imagen.size
        alto_mm = ANCHO_IMAGEN_MM * alto / ancho
        if self.get_y() + alto_mm > self.page_break_trigger:
            self.add_page()
        self.image(io.BytesIO(png), w=ANCHO_IMAGEN_MM)
        self.ln(3)

    def nota(self, texto: str) -> None:
        self.set_font(FUENTE_PDF, "I", 8)
        self.set_text_color(90, 90, 90)
        self.multi_cell(0, 4.5, texto, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0, 0, 0)


def escribir_pdf(reporte: Reporte, ruta: Path) -> Path:
    """PDF con encabezado en cada página, tablas, notas, gráficos y paginación (CA-13)."""
    pdf = _Pdf(reporte)
    for hoja in reporte.hojas:
        pdf.add_page()
        for tabla in hoja.tablas:
            pdf.tabla(tabla)
        for nota in hoja.notas:
            pdf.nota(nota)
        for png in hoja.imagenes:
            pdf.imagen(png)
    return _guardar(lambda: pdf.output(str(ruta)), ruta)


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
