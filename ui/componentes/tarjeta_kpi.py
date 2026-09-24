"""Tarjeta de un KPI: valor, semáforo con ícono y texto, variación y avisos (PAN-03, RNF-12)."""

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from core.analisis import estadistica as est
from core.analisis import semaforo
from core.analisis.kpis import ResultadoKPI
from core.reportes.catalogo import texto_variacion, formatear_valor
from core.reportes.graficos import COLORES_SEMAFORO

COLOR_NEUTRO = "#5A6B7B"


class TarjetaKPI(QFrame):
    def __init__(self, resultado: ResultadoKPI, descripcion: str = "", padre=None):
        super().__init__(padre)
        self.setObjectName("tarjetaKpi")
        self.setMinimumWidth(190)
        nombre = QLabel(f"{resultado.codigo} · {resultado.nombre}")
        nombre.setObjectName("tarjetaNombre")
        nombre.setWordWrap(True)
        valor = QLabel(formatear_valor(resultado, resultado.valor) + (" ≈" if resultado.aproximado else ""))
        valor.setObjectName("tarjetaValor")
        color = COLORES_SEMAFORO.get(resultado.semaforo, COLOR_NEUTRO)
        estado = QLabel(semaforo.etiqueta(resultado.semaforo))
        estado.setStyleSheet(f"color: {color}; font-weight: 600;")
        variacion = QLabel(f"vs. período anterior: {texto_variacion(resultado).replace(' puntos', ' pts')}")
        variacion.setToolTip("Variación frente al período anterior (pts = puntos porcentuales)")
        variacion.setObjectName("nota")
        diseno = QVBoxLayout(self)
        diseno.setSpacing(3)
        for widget in (nombre, valor, estado, variacion):
            diseno.addWidget(widget)
        if resultado.muestra_pequena:
            aviso = QLabel(est.AVISO_MUESTRA_PEQUENA)
            aviso.setStyleSheet("color: #8A5A00;")
            diseno.addWidget(aviso)
        self.setStyleSheet(f"QFrame#tarjetaKpi {{ border-left: 5px solid {color}; }}")
        ayuda = [descripcion] if descripcion else []
        ayuda += [f"Base de cálculo: {resultado.cantidad}"]
        if resultado.meta is not None:
            ayuda.append(f"Meta: {formatear_valor(resultado, resultado.meta)}")
        if resultado.p90 is not None:
            ayuda.append(f"P90: {resultado.p90:g} {resultado.unidad}")
        ayuda += [n for n in resultado.notas if n]
        self.setToolTip("\n".join(ayuda))
