"""Motor de KPIs predefinidos de la Fase 1 (spec 05; RN-01 a RN-07; CA-06).

Cada KPI se calcula para un período [inicio, fin) con filtros y a una fecha de
corte: el fin del período o ahora, si el período no ha terminado. Las gestiones
(KPI-04, KPI-05) son eventos de solución y de escalamiento (RN-07): se cuentan
eventos, no tickets, en el período en que ocurren.

La definición (umbrales, dirección, visibilidad) se lee de `kpi_definicion`; la
fórmula de cada predefinido está en `calculo_especial`. Los KPIs creados por el
usuario (KPI-00) llegan en la Fase 2.
"""

import sqlite3
import statistics
from collections.abc import Callable, Mapping
from functools import partial
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from core import parametros, reloj
from core.analisis import condiciones
from core.analisis import estadistica as est
from core.analisis import semaforo, sla
from core.analisis.filtros import Filtros, filtros_permitidos
from core.analisis.periodos import Periodo
from core.dominio import PRIORIDADES
from core.errores import ErrorValidacion
from core.importacion import eventos as ev
from core.seguridad import Sesion
from core.texto import normalizar_titulo

NOTA_APROXIMADO = (
    "≈ Aproximado: la fecha de solución es la última actualización del ticket en la "
    "importación en que apareció resuelto."
)
NOTA_SIN_SLA = "Defina los objetivos de SLA por prioridad en Configuración."

NOMBRE_PRIORIDAD = {p.nivel: p.nombre for p in PRIORIDADES}

# KPI-00: tipos de cálculo y campos de tiempo que ofrece el editor
TIPOS_CALCULO = {
    "CONTEO": "Conteo de tickets",
    "PORCENTAJE": "Porcentaje (numerador / denominador)",
    "MEDIANA_TIEMPO": "Mediana de tiempo",
    "PROMEDIO_TIEMPO": "Promedio de tiempo",
    "P90_TIEMPO": "P90 de tiempo",
}
TIPOS_TIEMPO = ("MEDIANA_TIEMPO", "PROMEDIO_TIEMPO", "P90_TIEMPO")
CAMPOS_TIEMPO = {"horas_resolucion": "Horas de resolución", "horas_hasta_cierre": "Horas hasta el cierre"}
UNIDAD_POR_TIPO = {"CONTEO": "tickets", "PORCENTAJE": "%", "MEDIANA_TIEMPO": "horas",
                   "PROMEDIO_TIEMPO": "horas", "P90_TIEMPO": "horas"}


@dataclass
class ResultadoKPI:
    codigo: str
    nombre: str
    unidad: str
    direccion: str
    valor: float | None
    numerador: float | None = None
    denominador: float | None = None
    cantidad: int = 0  # tickets o eventos sobre los que se calculó (RN-04)
    muestra_pequena: bool = False
    semaforo: str = semaforo.SIN_DATOS
    meta: float | None = None
    aproximado: bool = False
    critico: bool = False
    visible_dashboard: bool = True
    notas: list[str] = field(default_factory=list)
    detalle: list[dict] = field(default_factory=list)
    valor_anterior: float | None = None
    p90: float | None = None  # KPIs de tiempo

    @property
    def variacion_puntos(self) -> float | None:
        if self.valor is None or self.valor_anterior is None:
            return None
        return round(self.valor - self.valor_anterior, est.DECIMALES)

    @property
    def variacion_porcentual(self) -> float | None:
        if self.valor is None or not self.valor_anterior:
            return None
        return est.porcentaje(self.valor - self.valor_anterior, abs(self.valor_anterior))


def _iso(fecha: datetime) -> str:
    return fecha.isoformat(sep=" ")


class CalculadoraKPI:
    """Calcula KPIs con los parámetros y definiciones leídos una sola vez."""

    def __init__(self, conexion: sqlite3.Connection, sesion: Sesion, ahora: datetime | None = None):
        self.conexion = conexion
        self.sesion = sesion
        self.ahora = ahora or reloj.ahora()
        self.muestra_minima = parametros.entero(conexion, "muestra_minima")
        self.dias_sin_cerrar = parametros.entero(conexion, "dias_resuelto_sin_cerrar")
        self.objetivos_sla = sla.objetivos(conexion)
        self.horas_sin_actualizar = {
            p.nivel: parametros.decimal_opcional(conexion, f"horas_sin_actualizar_{p.clave}")
            for p in PRIORIDADES
        }
        self.umbrales_kpi06 = {
            p.nivel: (
                parametros.decimal_opcional(conexion, f"kpi06_verde_horas_{p.clave}"),
                parametros.decimal_opcional(conexion, f"kpi06_amarillo_horas_{p.clave}"),
            )
            for p in PRIORIDADES
        }
        self.definiciones = {
            fila["codigo"]: fila
            for fila in conexion.execute(
                "SELECT * FROM kpi_definicion WHERE activo = 1 ORDER BY orden"
            )
        }
        self._formulas: dict[str, Callable[[Periodo, Filtros, datetime], ResultadoKPI]] = {
            "KPI-01": self._kpi01_recibidos,
            "KPI-02": self._kpi02_resueltos,
            "KPI-03": self._kpi03_backlog,
            "KPI-04": self._kpi04_gestionados,
            "KPI-05": self._kpi05_escalamiento,
            "KPI-06": self._kpi06_tiempo_resolucion,
            "KPI-07": self._kpi07_sla,
            "KPI-08": self._kpi08_resueltos_sin_cerrar,
            "KPI-09": self._kpi09_completitud,
            "KPI-10": self._kpi10_otros,
            "KPI-11": self._kpi11_reincidencia,
            "KPI-12": self._kpi12_reaperturas,
            "KPI-13": self._kpi13_primera_respuesta,
            "KPI-14": self._kpi14_calidad,
            "KPI-15": self._kpi15_indice_general,
            "KPI-16": self._kpi16_sin_actualizar,
            "KPI-17": self._kpi17_tiempo_escalado,
        }

    # --- API ---

    def calcular(
        self, codigo: str, periodo: Periodo, filtros: Filtros = Filtros(), comparar: bool = True
    ) -> ResultadoKPI:
        """Valor, semáforo y variación frente al período anterior de un KPI."""
        definicion = self.definiciones.get(codigo)
        if definicion is None:
            raise ErrorValidacion(f"El KPI «{codigo}» no existe o está inactivo.")
        return self.calcular_definicion(definicion, periodo, filtros, comparar)

    def calcular_definicion(
        self, definicion: Mapping, periodo: Periodo, filtros: Filtros = Filtros(), comparar: bool = True
    ) -> ResultadoKPI:
        """Calcula una definición guardada o en edición (vista previa del editor, KPI-00)."""
        if definicion["calculo_especial"]:
            formula = self._formulas.get(definicion["calculo_especial"])
            if formula is None:
                raise ErrorValidacion(f"El KPI «{definicion['nombre']}» tiene una fórmula desconocida.")
        else:
            formula = partial(self._generico, definicion)
        filtros = filtros_permitidos(self.sesion, filtros)
        resultado = self._completar(formula(periodo, filtros, periodo.corte(self.ahora)), definicion)
        if comparar:
            anterior = periodo.anterior()
            previo = formula(anterior, filtros, anterior.corte(self.ahora))
            resultado.valor_anterior = previo.valor
        return resultado

    def calcular_visibles(self, periodo: Periodo, filtros: Filtros = Filtros()) -> list[ResultadoKPI]:
        """Los KPIs marcados como visibles en el dashboard, en su orden."""
        return [
            self.calcular(codigo, periodo, filtros)
            for codigo, definicion in self.definiciones.items()
            if definicion["visible_dashboard"]
        ]

    # --- KPIs creados por el usuario (KPI-00) ---

    def _generico(self, definicion: Mapping, periodo: Periodo, filtros: Filtros, corte: datetime) -> ResultadoKPI:
        """CONTEO y PORCENTAJE sobre los tickets recibidos en el período; los tiempos,
        sobre los resueltos en el período. El numerador de un porcentaje cumple además
        las condiciones del denominador, así que nunca supera 100 %."""
        codigo = definicion["codigo"]
        tipo = definicion["tipo_calculo"]
        numerador = condiciones.leer(definicion["filtro_numerador_json"])
        condicion_global, valores_global = filtros.sql("t")
        base = "FROM ticket t LEFT JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi WHERE "

        if tipo in TIPOS_TIEMPO:
            campo = definicion["campo_tiempo"]
            if campo not in CAMPOS_TIEMPO:
                raise ErrorValidacion(f"El KPI «{definicion['nombre']}» necesita un campo de tiempo válido.")
            condicion, valores = condiciones.a_sql(numerador)
            filas = self.conexion.execute(
                f"SELECT t.{campo} {base}t.fecha_solucion >= ? AND t.fecha_solucion < ?"
                f"{condicion_global}{condicion}",
                [_iso(periodo.inicio), _iso(periodo.fin), *valores_global, *valores],
            ).fetchall()
            resumen = est.resumir_tiempos((f[0] for f in filas), self.muestra_minima)
            valor = {"MEDIANA_TIEMPO": resumen.mediana, "PROMEDIO_TIEMPO": resumen.promedio,
                     "P90_TIEMPO": resumen.p90}[tipo]
            return self._base(codigo, valor, cantidad=resumen.cantidad, p90=resumen.p90,
                              notas=[est.AVISO_SIN_ESPERA])

        def contar(lista: list[dict]) -> int:
            condicion, valores = condiciones.a_sql(lista)
            return self._escalar(
                f"SELECT COUNT(*) {base}t.fecha_apertura >= ? AND t.fecha_apertura < ?{condicion_global}{condicion}",
                [_iso(periodo.inicio), _iso(periodo.fin), *valores_global, *valores],
            )

        if tipo == "CONTEO":
            cantidad = contar(numerador)
            return self._base(codigo, float(cantidad), cantidad=cantidad)
        if tipo == "PORCENTAJE":
            denominador = condiciones.leer(definicion["filtro_denominador_json"])
            base_calculo = contar(denominador)
            parte = contar(denominador + numerador)
            return self._base(codigo, est.porcentaje(parte, base_calculo), numerador=parte,
                              denominador=base_calculo, cantidad=base_calculo)
        raise ErrorValidacion(f"Tipo de cálculo no disponible: «{tipo}».")

    # --- Apoyo ---

    def _completar(self, resultado: ResultadoKPI, definicion: Mapping) -> ResultadoKPI:
        resultado = replace(
            resultado,
            nombre=definicion["nombre"],
            unidad=definicion["unidad"],
            direccion=definicion["direccion"],
            meta=definicion["meta"],
            aproximado=bool(definicion["aproximado"]),
            critico=bool(definicion["critico"]),
            visible_dashboard=bool(definicion["visible_dashboard"]),
        )
        resultado.muestra_pequena = est.muestra_pequena(resultado.cantidad, self.muestra_minima)
        if resultado.semaforo == semaforo.SIN_DATOS:
            resultado.semaforo = semaforo.evaluar(
                resultado.valor, definicion["direccion"],
                definicion["umbral_verde"], definicion["umbral_amarillo"],
            )
        if resultado.aproximado and NOTA_APROXIMADO not in resultado.notas:
            resultado.notas.append(NOTA_APROXIMADO)
        return resultado

    def _base(self, codigo: str, valor, **otros) -> ResultadoKPI:
        return ResultadoKPI(codigo=codigo, nombre="", unidad="", direccion="", valor=valor, **otros)

    def _escalar(self, sql: str, parametros_sql: list) -> int:
        return self.conexion.execute(sql, parametros_sql).fetchone()[0]

    def _recibidos(self, periodo: Periodo, filtros: Filtros) -> int:
        condicion, valores = filtros.sql("t")
        return self._escalar(
            "SELECT COUNT(*) FROM ticket t WHERE t.fecha_apertura >= ? AND t.fecha_apertura < ?"
            + condicion,
            [_iso(periodo.inicio), _iso(periodo.fin), *valores],
        )

    def contar_eventos(self, tipo: str, periodo: Periodo, filtros: Filtros, distintos: bool = False) -> int:
        condicion, valores = filtros.sql("t")
        contar = "COUNT(DISTINCT e.ticket_id)" if distintos else "COUNT(*)"
        return self._escalar(
            f"SELECT {contar} FROM ticket_evento e JOIN ticket t ON t.id_glpi = e.ticket_id "
            "WHERE e.tipo = ? AND e.fecha_evento >= ? AND e.fecha_evento < ?" + condicion,
            [tipo, _iso(periodo.inicio), _iso(periodo.fin), *valores],
        )

    @staticmethod
    def _cte_ultimo_evento(tipos: tuple[str, ...]) -> str:
        """CTE `ultimo` con un parámetro (la fecha de corte): el último evento de cada
        ticket, entre `tipos`, anterior al corte. Una fila por ticket.

        Se calcula en una sola pasada con ROW_NUMBER. Quien la usa debe consultarla con
        IN / NOT IN o recorriéndola primero (CROSS JOIN): SQLite no le crea índice, y
        unirla por la derecha con LEFT JOIN la recorre entera por cada ticket.
        Los tipos son constantes del código.
        """
        marcas = ", ".join(f"'{t}'" for t in tipos)
        return (
            "WITH ultimo AS (SELECT ticket_id, tipo, fecha_evento FROM ("
            "SELECT ticket_id, tipo, fecha_evento, ROW_NUMBER() OVER ("
            "PARTITION BY ticket_id ORDER BY fecha_evento DESC, id DESC) AS n "
            f"FROM ticket_evento WHERE tipo IN ({marcas}) AND fecha_evento < ?) WHERE n = 1) "
        )

    def abiertos_al_corte(self, filtros: Filtros, corte: datetime) -> list[sqlite3.Row]:
        """Tickets abiertos a la fecha de corte, con los permisos de la sesión."""
        return self._abiertos_al_corte(filtros_permitidos(self.sesion, filtros), corte)

    def _abiertos_al_corte(self, filtros: Filtros, corte: datetime) -> list[sqlite3.Row]:
        """Tickets abiertos a la fecha de corte: abiertos antes del corte y cuyo último
        evento de solución o reapertura no es una solución."""
        condicion, valores = filtros.sql("t")
        return self.conexion.execute(
            self._cte_ultimo_evento((ev.SOLUCION, ev.REAPERTURA))
            + "SELECT t.id_glpi, t.prioridad_nivel, t.ultima_actualizacion, t.tecnico_principal_id "
            "FROM ticket t "
            "WHERE t.fecha_apertura < ? AND t.id_glpi NOT IN "
            f"(SELECT ticket_id FROM ultimo WHERE tipo = '{ev.SOLUCION}')"
            + condicion,
            [_iso(corte), _iso(corte), *valores],
        ).fetchall()

    def _resueltos_en(self, periodo: Periodo, filtros: Filtros) -> list[sqlite3.Row]:
        """Tickets cuya fecha de solución vigente cae en el período."""
        condicion, valores = filtros.sql("t")
        return self.conexion.execute(
            "SELECT t.id_glpi, t.prioridad_nivel, t.horas_resolucion FROM ticket t "
            "WHERE t.fecha_solucion >= ? AND t.fecha_solucion < ?" + condicion,
            [_iso(periodo.inicio), _iso(periodo.fin), *valores],
        ).fetchall()

    # --- Fórmulas ---

    def _kpi01_recibidos(self, periodo, filtros, corte) -> ResultadoKPI:
        cantidad = self._recibidos(periodo, filtros)
        return self._base("KPI-01", float(cantidad), cantidad=cantidad)

    def _kpi02_resueltos(self, periodo, filtros, corte) -> ResultadoKPI:
        cantidad = self.contar_eventos(ev.SOLUCION, periodo, filtros, distintos=True)
        return self._base("KPI-02", float(cantidad), cantidad=cantidad)

    def _kpi03_backlog(self, periodo, filtros, corte) -> ResultadoKPI:
        abiertos = self._abiertos_al_corte(filtros, corte)
        detalle = [
            {"prioridad": NOMBRE_PRIORIDAD[nivel], "abiertos": sum(1 for a in abiertos if a["prioridad_nivel"] == nivel)}
            for nivel in sorted(NOMBRE_PRIORIDAD, reverse=True)
        ]
        return self._base("KPI-03", float(len(abiertos)), cantidad=len(abiertos), detalle=detalle)

    def _kpi04_gestionados(self, periodo, filtros, corte) -> ResultadoKPI:
        soluciones = self.contar_eventos(ev.SOLUCION, periodo, filtros)
        escalamientos = self.contar_eventos(ev.ESCALAMIENTO, periodo, filtros)
        recibidos = self._recibidos(periodo, filtros)
        gestiones = soluciones + escalamientos
        return self._base(
            "KPI-04", est.porcentaje(gestiones, recibidos), numerador=gestiones,
            denominador=recibidos, cantidad=recibidos,
            detalle=[{"soluciones": soluciones, "escalamientos": escalamientos, "recibidos": recibidos}],
        )

    def _kpi05_escalamiento(self, periodo, filtros, corte) -> ResultadoKPI:
        soluciones = self.contar_eventos(ev.SOLUCION, periodo, filtros)
        escalamientos = self.contar_eventos(ev.ESCALAMIENTO, periodo, filtros)
        gestiones = soluciones + escalamientos
        return self._base(
            "KPI-05", est.porcentaje(escalamientos, gestiones), numerador=escalamientos,
            denominador=gestiones, cantidad=gestiones,
            detalle=[{"soluciones": soluciones, "escalamientos": escalamientos}],
        )

    def _kpi06_tiempo_resolucion(self, periodo, filtros, corte) -> ResultadoKPI:
        resueltos = self._resueltos_en(periodo, filtros)
        resumen = est.resumir_tiempos((r["horas_resolucion"] for r in resueltos), self.muestra_minima)
        detalle, colores = [], []
        for nivel in sorted(NOMBRE_PRIORIDAD, reverse=True):
            horas = [r["horas_resolucion"] for r in resueltos if r["prioridad_nivel"] == nivel]
            if not horas:
                continue
            parcial = est.resumir_tiempos(horas, self.muestra_minima)
            verde, amarillo = self.umbrales_kpi06[nivel]
            color = semaforo.evaluar(parcial.mediana, semaforo.MENOR_MEJOR, verde, amarillo)
            colores.append(color)
            detalle.append({
                "prioridad": NOMBRE_PRIORIDAD[nivel], "tickets": parcial.cantidad,
                "mediana": parcial.mediana, "p90": parcial.p90, "promedio": parcial.promedio,
                "muestra_pequena": parcial.muestra_pequena, "semaforo": color,
            })
        # El semáforo global es el peor de las prioridades con umbrales definidos
        color = semaforo.peor(colores)
        if color == semaforo.SIN_DATOS and resumen.mediana is not None:
            color = semaforo.INFORMATIVO
        notas = [est.AVISO_SIN_ESPERA]
        if resumen.p90 is not None:
            notas.append(f"P90: {resumen.p90} h")
        return self._base(
            "KPI-06", resumen.mediana, cantidad=resumen.cantidad, detalle=detalle,
            semaforo=color, notas=notas, p90=resumen.p90,
        )

    def _kpi07_sla(self, periodo, filtros, corte) -> ResultadoKPI:
        resueltos = self._resueltos_en(periodo, filtros)
        con_objetivo = [
            r for r in resueltos
            if self.objetivos_sla.get(r["prioridad_nivel"]) is not None and r["horas_resolucion"] is not None
        ]
        a_tiempo = sum(
            sla.a_tiempo(r["horas_resolucion"], self.objetivos_sla[r["prioridad_nivel"]]) for r in con_objetivo
        )
        notas = [est.AVISO_SIN_ESPERA]
        if all(v is None for v in self.objetivos_sla.values()):
            notas.insert(0, NOTA_SIN_SLA)
        return self._base(
            "KPI-07", est.porcentaje(a_tiempo, len(con_objetivo)), numerador=a_tiempo,
            denominador=len(con_objetivo), cantidad=len(con_objetivo), notas=notas,
        )

    def _kpi08_resueltos_sin_cerrar(self, periodo, filtros, corte) -> ResultadoKPI:
        """De los tickets resueltos en el período, los que a la fecha de corte siguen en
        Resuelto (sin cierre ni reapertura) desde hace más de `dias_resuelto_sin_cerrar`."""
        condicion, valores = filtros.sql("t")
        limite = corte - timedelta(days=self.dias_sin_cerrar)
        # Si el último evento (solución, cierre o reapertura) es la solución, su fecha
        # es la de la solución vigente
        # Todo ticket resuelto en el período tiene al menos ese evento antes del corte,
        # así que siempre aparece en `ultimo`
        filas = self.conexion.execute(
            self._cte_ultimo_evento((ev.SOLUCION, ev.CIERRE, ev.REAPERTURA))
            + "SELECT t.id_glpi, u.tipo AS ultimo, u.fecha_evento AS fecha "
            "FROM ultimo u CROSS JOIN ticket t ON t.id_glpi = u.ticket_id "
            "WHERE u.ticket_id IN (SELECT ticket_id FROM ticket_evento "
            f" WHERE tipo = '{ev.SOLUCION}' AND fecha_evento >= ? AND fecha_evento < ?)"
            + condicion,
            [_iso(corte), _iso(periodo.inicio), _iso(periodo.fin), *valores],
        ).fetchall()
        sin_cerrar = sum(
            1 for f in filas
            if f["ultimo"] == ev.SOLUCION and datetime.fromisoformat(f["fecha"]) < limite
        )
        return self._base(
            "KPI-08", est.porcentaje(sin_cerrar, len(filas)), numerador=sin_cerrar,
            denominador=len(filas), cantidad=len(filas),
        )

    def _kpi09_completitud(self, periodo, filtros, corte) -> ResultadoKPI:
        """Resueltos del período con los cuatro campos de la clasificación manual."""
        condicion, valores = filtros.sql("t")
        fila = self.conexion.execute(
            "SELECT COUNT(*) AS resueltos, SUM(c.estacion_id IS NOT NULL AND c.categoria_codigo IS NOT NULL "
            "AND c.causa_codigo IS NOT NULL AND c.tipo_solucion_codigo IS NOT NULL) AS completos "
            "FROM ticket t LEFT JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
            "WHERE t.fecha_solucion >= ? AND t.fecha_solucion < ?" + condicion,
            [_iso(periodo.inicio), _iso(periodo.fin), *valores],
        ).fetchone()
        resueltos, completos = fila["resueltos"], fila["completos"] or 0
        return self._base("KPI-09", est.porcentaje(completos, resueltos), numerador=completos,
                          denominador=resueltos, cantidad=resueltos)

    def _kpi10_otros(self, periodo, filtros, corte) -> ResultadoKPI:
        """Recibidos del período con categoría asignada: cuántos quedaron en OTR-01."""
        condicion, valores = filtros.sql("t")
        fila = self.conexion.execute(
            "SELECT COUNT(*) AS clasificados, SUM(c.categoria_codigo = 'OTR-01') AS otros FROM ticket t "
            "JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
            "WHERE c.categoria_codigo IS NOT NULL AND t.fecha_apertura >= ? AND t.fecha_apertura < ?" + condicion,
            [_iso(periodo.inicio), _iso(periodo.fin), *valores],
        ).fetchone()
        clasificados, otros = fila["clasificados"], fila["otros"] or 0
        return self._base("KPI-10", est.porcentaje(otros, clasificados), numerador=otros,
                          denominador=clasificados, cantidad=clasificados)

    def _kpi11_reincidencia(self, periodo, filtros, corte) -> ResultadoKPI:
        """Recibidos con estación cuyo caso (estación + título normalizado) tuvo otro
        ticket en los `reincidencia_dias` días anteriores a su apertura."""
        dias = parametros.entero(self.conexion, "reincidencia_dias")
        condicion, valores = filtros.sql("t")
        contados = self.conexion.execute(
            "SELECT t.id_glpi FROM ticket t JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
            "WHERE c.estacion_id IS NOT NULL AND t.fecha_apertura >= ? AND t.fecha_apertura < ?" + condicion,
            [_iso(periodo.inicio), _iso(periodo.fin), *valores],
        ).fetchall()
        ids = {f[0] for f in contados}
        ventana = self.conexion.execute(
            "SELECT t.id_glpi, t.titulo, t.fecha_apertura, c.estacion_id FROM ticket t "
            "JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
            "WHERE c.estacion_id IS NOT NULL AND t.fecha_apertura >= ? AND t.fecha_apertura < ?",
            [_iso(periodo.inicio - timedelta(days=dias)), _iso(periodo.fin)],
        ).fetchall()
        por_caso: dict[tuple, list[datetime]] = {}
        for fila in ventana:
            clave = (fila["estacion_id"], normalizar_titulo(fila["titulo"]))
            por_caso.setdefault(clave, []).append(datetime.fromisoformat(fila["fecha_apertura"]))
        reincidentes = 0
        for fila in ventana:
            if fila["id_glpi"] not in ids:
                continue
            apertura = datetime.fromisoformat(fila["fecha_apertura"])
            otras = por_caso[(fila["estacion_id"], normalizar_titulo(fila["titulo"]))]
            if any(apertura - timedelta(days=dias) <= o < apertura for o in otras):
                reincidentes += 1
        return self._base("KPI-11", est.porcentaje(reincidentes, len(ids)), numerador=reincidentes,
                          denominador=len(ids), cantidad=len(ids))

    def _kpi12_reaperturas(self, periodo, filtros, corte) -> ResultadoKPI:
        reaperturas = self.contar_eventos(ev.REAPERTURA, periodo, filtros)
        resueltos = self.contar_eventos(ev.SOLUCION, periodo, filtros, distintos=True)
        return self._base("KPI-12", est.porcentaje(reaperturas, resueltos), numerador=reaperturas,
                          denominador=resueltos, cantidad=resueltos)

    def _kpi13_primera_respuesta(self, periodo, filtros, corte) -> ResultadoKPI:
        """Horas de la apertura al primer seguimiento o tarea (requiere el CSV de seguimientos)."""
        condicion, valores = filtros.sql("t")
        filas = self.conexion.execute(
            "SELECT t.fecha_apertura, (SELECT MIN(s.fecha) FROM seguimiento s WHERE s.ticket_id = t.id_glpi "
            "AND s.tipo IN ('SEGUIMIENTO', 'TAREA')) AS primera FROM ticket t "
            "WHERE t.fecha_apertura >= ? AND t.fecha_apertura < ?" + condicion,
            [_iso(periodo.inicio), _iso(periodo.fin), *valores],
        ).fetchall()
        horas = [
            max(0.0, (datetime.fromisoformat(f["primera"]) - datetime.fromisoformat(f["fecha_apertura"])).total_seconds() / 3600)
            for f in filas if f["primera"]
        ]
        resumen = est.resumir_tiempos(horas, self.muestra_minima)
        notas = [] if horas else ["Importe el CSV de seguimientos para calcular la primera respuesta."]
        return self._base("KPI-13", resumen.mediana, cantidad=resumen.cantidad, p90=resumen.p90, notas=notas)

    def _kpi14_calidad(self, periodo, filtros, corte) -> ResultadoKPI:
        """Promedio del % de las evaluaciones vigentes hechas en el período (CAL-03)."""
        condicion, valores = filtros.sql("t")
        fila = self.conexion.execute(
            "SELECT AVG(v.porcentaje) AS promedio, COUNT(*) AS cantidad FROM evaluacion v "
            "JOIN ticket t ON t.id_glpi = v.ticket_id WHERE v.vigente = 1 AND v.porcentaje IS NOT NULL "
            "AND v.fecha >= ? AND v.fecha < ?" + condicion,
            [_iso(periodo.inicio), _iso(periodo.fin), *valores],
        ).fetchone()
        valor = None if fila["promedio"] is None else round(fila["promedio"], est.DECIMALES)
        notas = [] if fila["cantidad"] else ["Sin evaluaciones de calidad en el período."]
        return self._base("KPI-14", valor, cantidad=fila["cantidad"], notas=notas)

    def _kpi15_indice_general(self, periodo, filtros, corte) -> ResultadoKPI:
        """Peso de calidad × KPI-14 + resto × operativo (promedio de KPI-04 con tope 100, KPI-07
        y 100 − KPI-08). Si falta algún componente operativo se promedian los disponibles."""
        peso_calidad = (parametros.decimal_opcional(self.conexion, "kpi15_peso_calidad") or 60) / 100
        calidad = self._kpi14_calidad(periodo, filtros, corte).valor
        gestionados = self._kpi04_gestionados(periodo, filtros, corte).valor
        sla_valor = self._kpi07_sla(periodo, filtros, corte).valor
        sin_cerrar = self._kpi08_resueltos_sin_cerrar(periodo, filtros, corte).valor
        operativos = [v for v in (
            None if gestionados is None else min(gestionados, 100.0),
            sla_valor,
            None if sin_cerrar is None else 100 - sin_cerrar,
        ) if v is not None]
        notas = ["Componentes por confirmar con la hoja KPI_SOPORTE del libro de control."]
        if calidad is None or not operativos:
            notas.insert(0, "Faltan evaluaciones de calidad o datos operativos para calcular el índice.")
            return self._base("KPI-15", None, notas=notas)
        operativo = statistics.fmean(operativos)
        valor = round(peso_calidad * calidad + (1 - peso_calidad) * operativo, est.DECIMALES)
        detalle = [{"calidad": calidad, "operativo": round(operativo, est.DECIMALES), "peso_calidad": peso_calidad}]
        return self._base("KPI-15", valor, cantidad=len(operativos), detalle=detalle, notas=notas)

    def _kpi16_sin_actualizar(self, periodo, filtros, corte) -> ResultadoKPI:
        abiertos = self._abiertos_al_corte(filtros, corte)
        sin_actualizar = 0
        for ticket in abiertos:
            umbral = self.horas_sin_actualizar.get(ticket["prioridad_nivel"])
            ultima = datetime.fromisoformat(ticket["ultima_actualizacion"])
            if umbral is not None and ultima < corte and corte - ultima > timedelta(hours=umbral):
                sin_actualizar += 1
        return self._base(
            "KPI-16", est.porcentaje(sin_actualizar, len(abiertos)), numerador=sin_actualizar,
            denominador=len(abiertos), cantidad=len(abiertos),
        )

    def _kpi17_tiempo_escalado(self, periodo, filtros, corte) -> ResultadoKPI:
        """Horas entre cada escalamiento y su salida, para las salidas del período."""
        condicion, valores = filtros.sql("t")
        filas = self.conexion.execute(
            "SELECT e.ticket_id, e.tipo, e.fecha_evento FROM ticket_evento e "
            "JOIN ticket t ON t.id_glpi = e.ticket_id WHERE e.tipo IN (?, ?) "
            "AND e.fecha_evento < ?" + condicion + " ORDER BY e.ticket_id, e.fecha_evento, e.id",
            [ev.ESCALAMIENTO, ev.SALIDA_ESCALADO, _iso(periodo.fin), *valores],
        ).fetchall()
        duraciones = []
        abierto: dict[int, datetime] = {}
        for fila in filas:
            fecha = datetime.fromisoformat(fila["fecha_evento"])
            if fila["tipo"] == ev.ESCALAMIENTO:
                abierto[fila["ticket_id"]] = fecha
            elif fila["ticket_id"] in abierto:
                inicio = abierto.pop(fila["ticket_id"])
                if periodo.contiene(fecha):
                    duraciones.append((fecha - inicio).total_seconds() / 3600)
        resumen = est.resumir_tiempos(duraciones, self.muestra_minima)
        return self._base("KPI-17", resumen.mediana, cantidad=resumen.cantidad, p90=resumen.p90)


def criticidad_global(resultados: list[ResultadoKPI]) -> str:
    """Peor semáforo entre los KPIs marcados como críticos."""
    return semaforo.peor(r.semaforo for r in resultados if r.critico)
