"""Notificaciones de la aplicación offline (spec 09): NOT-01 a NOT-05.

Se calculan al vuelo; no se guardan.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from core import parametros, reloj
from core.analisis import calidad_metricas, hallazgos, periodos, semaforo
from core.analisis.kpis import CalculadoraKPI
from core.importacion import carga
from core.seguridad import Sesion

AL_INICIAR = "AL_INICIAR"
DESPUES_DE_IMPORTAR = "DESPUES_DE_IMPORTAR"


@dataclass(frozen=True)
class Notificacion:
    codigo: str
    severidad: str
    mensaje: str
    accion: str | None = None  # pantalla sugerida


def _not01(conexion: sqlite3.Connection, ahora: datetime) -> list[Notificacion]:
    ultima = carga.ultima_importacion(conexion)
    dias = parametros.entero(conexion, "dias_importacion_desactualizada")
    if ultima is not None and (ahora - ultima).days < dias:
        return []
    texto = "Todavía no hay importaciones." if ultima is None else \
        f"La última importación es del {ultima:%d/%m/%Y %H:%M} (más de {dias} día(s))."
    return [Notificacion("NOT-01", "MEDIA", f"{texto} Importe una exportación reciente de GLPI.", "Importar")]


def _not02(conexion: sqlite3.Connection, sesion: Sesion) -> list[Notificacion]:
    altas = hallazgos.conteo_nuevos(conexion, sesion)[hallazgos.ALTA]
    if not altas:
        return []
    return [Notificacion("NOT-02", "ALTA", f"Hay {altas} hallazgo(s) nuevo(s) de severidad ALTA.", "Hallazgos")]


def _not03(conexion: sqlite3.Connection, sesion: Sesion, ahora: datetime) -> list[Notificacion]:
    if not sesion.es_coordinador or not conexion.execute("SELECT EXISTS (SELECT 1 FROM ticket)").fetchone()[0]:
        return []
    anterior = periodos.mes_de(ahora).anterior()
    generado = conexion.execute("SELECT 1 FROM paquete_mensual WHERE periodo = ?", (anterior.codigo,)).fetchone()
    if generado:
        return []
    return [Notificacion("NOT-03", "MEDIA", f"El paquete mensual de {anterior.etiqueta} todavía no se ha generado.",
                         "Reportes")]


def _not05(conexion: sqlite3.Connection, sesion: Sesion, ahora: datetime) -> list[Notificacion]:
    calc = CalculadoraKPI(conexion, sesion, ahora)
    mes = periodos.mes_de(ahora)
    rojos = [
        f"{codigo} {d['nombre']}" for codigo, d in calc.definiciones.items()
        if d["critico"] and calc.calcular(codigo, mes, comparar=False).semaforo == semaforo.ROJO
    ]
    if not rojos:
        return []
    return [Notificacion("NOT-05", "ALTA", f"KPI crítico en rojo en {mes.etiqueta}: {', '.join(rojos)}.", "Dashboard")]


def _not04(conexion: sqlite3.Connection, sesion: Sesion, ahora: datetime) -> list[Notificacion]:
    """Los lunes: tickets de la muestra de la semana anterior sin evaluar (CAL-04)."""
    if not sesion.es_coordinador or ahora.weekday() != 0:
        return []
    pendientes_calidad = calidad_metricas.evaluaciones_pendientes(conexion, ahora)
    if not pendientes_calidad:
        return []
    return [Notificacion("NOT-04", "MEDIA", f"Hay {pendientes_calidad} ticket(s) de la muestra semanal sin evaluar.",
                         "Calidad")]


def pendientes(conexion: sqlite3.Connection, sesion: Sesion, momento: str, ahora: datetime | None = None) -> list[Notificacion]:
    """NOT-01 a NOT-04 al iniciar; NOT-02 y NOT-05 después de importar."""
    ahora = ahora or reloj.ahora()
    if momento == AL_INICIAR:
        return (_not01(conexion, ahora) + _not02(conexion, sesion) + _not03(conexion, sesion, ahora)
                + _not04(conexion, sesion, ahora))
    return _not02(conexion, sesion) + _not05(conexion, sesion, ahora)
