"""Figuras de matplotlib, las mismas para la interfaz y para los reportes.

Se usa `Figure` directamente (sin pyplot) para poder crearlas desde cualquier hilo.
La interfaz las muestra con FigureCanvasQTAgg; los reportes las guardan como PNG.
"""

import io

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from core.analisis.semaforo import AMARILLO, ROJO, VERDE
from core.analisis.series import Brecha, PuntoSerie

AZUL_MARINO = "#1F3A5F"
AZUL = "#2E86AB"
GRIS = "#9AA5B1"
COLORES_SEMAFORO = {VERDE: "#2E7D32", AMARILLO: "#F9A825", ROJO: "#C62828"}
COLORES_PRIORIDAD = {
    "Mayor": "#7B1FA2", "Muy urgente": "#C62828", "Urgente": "#EF6C00",
    "Mediana": "#2E86AB", "Baja": "#66BB6A", "Muy baja": "#9AA5B1",
}
TAMANO = (6.4, 3.4)
FUENTE = ["Segoe UI", "DejaVu Sans"]


def _figura(titulo: str) -> tuple[Figure, object]:
    figura = Figure(figsize=TAMANO, dpi=100, layout="constrained")
    ejes = figura.add_subplot()
    ejes.set_title(titulo, fontsize=11, color=AZUL_MARINO, loc="left", fontfamily=FUENTE)
    ejes.spines[["top", "right"]].set_visible(False)
    ejes.tick_params(labelsize=8)
    return figura, ejes


def _sin_datos(ejes) -> None:
    ejes.text(0.5, 0.5, "Sin datos para el período", ha="center", va="center",
              transform=ejes.transAxes, color=GRIS, fontsize=10)
    ejes.set_xticks([])
    ejes.set_yticks([])


def recibidos_resueltos(serie: list[PuntoSerie]) -> Figure:
    figura, ejes = _figura("Recibidos vs. resueltos")
    if not serie or not any(any(v for v in p.valores.values()) for p in serie):
        _sin_datos(ejes)
        return figura
    etiquetas = [p.etiqueta for p in serie]
    posiciones = range(len(serie))
    ancho = 0.4
    ejes.bar([x - ancho / 2 for x in posiciones], [p.valores["Recibidos"] or 0 for p in serie],
             ancho, label="Recibidos", color=AZUL_MARINO)
    ejes.bar([x + ancho / 2 for x in posiciones], [p.valores["Resueltos"] or 0 for p in serie],
             ancho, label="Resueltos", color=AZUL)
    ejes.set_xticks(list(posiciones), etiquetas, rotation=45 if len(serie) > 8 else 0)
    ejes.legend(fontsize=8, frameon=False)
    return figura


def backlog(serie: list[PuntoSerie]) -> Figure:
    figura, ejes = _figura("Backlog al cierre de cada período")
    if not serie:
        _sin_datos(ejes)
        return figura
    ejes.plot([p.etiqueta for p in serie], [p.valores["Backlog"] or 0 for p in serie],
              marker="o", color=AZUL_MARINO)
    ejes.tick_params(axis="x", rotation=45 if len(serie) > 8 else 0)
    ejes.set_ylim(bottom=0)
    return figura


def barras(conteos: dict[str, int], titulo: str, colores: dict[str, str] | None = None) -> Figure:
    figura, ejes = _figura(titulo)
    if not any(conteos.values()):
        _sin_datos(ejes)
        return figura
    nombres = list(conteos)
    color = [(colores or {}).get(n, AZUL_MARINO) for n in nombres]
    barras_h = ejes.barh(nombres, list(conteos.values()), color=color)
    ejes.bar_label(barras_h, fontsize=8, padding=2)
    ejes.invert_yaxis()
    return figura


def carga_por_tecnico(carga: dict[str, dict[str, int]]) -> Figure:
    figura, ejes = _figura("Carga por técnico (abiertos)")
    if not carga:
        _sin_datos(ejes)
        return figura
    tecnicos = list(carga)
    izquierda = [0] * len(tecnicos)
    for prioridad, color in COLORES_PRIORIDAD.items():
        valores = [carga[t].get(prioridad, 0) for t in tecnicos]
        if any(valores):
            ejes.barh(tecnicos, valores, left=izquierda, color=color, label=prioridad)
            izquierda = [a + b for a, b in zip(izquierda, valores)]
    ejes.invert_yaxis()
    ejes.legend(fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    return figura


def brecha_vs_meta(brechas: list[Brecha]) -> Figure:
    figura, ejes = _figura("Brecha frente a la meta")
    if not brechas:
        _sin_datos(ejes)
        return figura
    nombres = [f"{b.codigo} {b.nombre}" for b in brechas]
    colores = [COLORES_SEMAFORO.get(b.semaforo, GRIS) for b in brechas]
    barras_h = ejes.barh(nombres, [b.valor for b in brechas], color=colores, label="Valor")
    ejes.bar_label(barras_h, labels=[f"{b.valor:g} %" for b in brechas], fontsize=8, padding=2)
    for indice, b in enumerate(brechas):
        ejes.plot([b.objetivo, b.objetivo], [indice - 0.4, indice + 0.4], color="black", linewidth=2)
    ejes.plot([], [], color="black", linewidth=2, label="Meta o umbral verde")
    ejes.invert_yaxis()
    ejes.legend(fontsize=7, frameon=False, loc="lower right")
    return figura


def tendencia(puntos: list, titulo: str, unidad: str = "") -> Figure:
    """Línea con los valores guardados en snapshot (tendencias de 6 y 12 meses)."""
    figura, ejes = _figura(titulo)
    con_valor = [p for p in puntos if p.valor is not None]
    if not con_valor:
        _sin_datos(ejes)
        ejes.text(0.5, 0.35, "Genere snapshots de meses cerrados para ver la tendencia", ha="center",
                  transform=ejes.transAxes, color=GRIS, fontsize=8)
        return figura
    ejes.plot([p.periodo for p in con_valor], [p.valor for p in con_valor], marker="o", color=AZUL_MARINO)
    for p in con_valor:
        ejes.annotate(f"{p.valor:g}", (p.periodo, p.valor), textcoords="offset points", xytext=(0, 6),
                      ha="center", fontsize=7)
    ejes.set_ylabel(unidad, fontsize=8)
    ejes.tick_params(axis="x", rotation=45 if len(con_valor) > 6 else 0)
    return figura


def a_png(figura: Figure, dpi: int = 110) -> bytes:
    """PNG de la figura, para Excel y PDF."""
    FigureCanvasAgg(figura)
    salida = io.BytesIO()
    figura.savefig(salida, format="png", dpi=dpi)
    return salida.getvalue()
