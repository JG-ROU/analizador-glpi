"""Hallazgos automáticos HAL-01 a HAL-12 (spec 08, ajustada en 12).

Se ejecutan después de cada importación, al iniciar y bajo demanda. Un hallazgo se
identifica por regla + entidad + período: si se vuelve a detectar, se actualizan
sus datos (no se duplica) y se conserva su estado de revisión. Los hallazgos de
"situación actual" (período ACTUAL) se cierran solos cuando la situación termina.
Los umbrales están en la tabla `parametro`.
"""

import json
import logging
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from core import historial, parametros, reloj, seguridad
from core.analisis import periodos, semaforo
from core.analisis.kpis import NOMBRE_PRIORIDAD, CalculadoraKPI
from core.dominio import PRIORIDADES
from core.errores import ErrorValidacion
from core.importacion import carga
from core.importacion import eventos as ev
from core.seguridad import Sesion
from core.texto import normalizar_titulo

log = logging.getLogger(__name__)

ALTA, MEDIA, BAJA = "ALTA", "MEDIA", "BAJA"
NUEVO, REVISADO, DESCARTADO, CERRADO = "NUEVO", "REVISADO", "DESCARTADO", "CERRADO"
ACTUAL = "ACTUAL"
PRIORIDAD_ALTA = 4  # «alta» de la spec: Urgente y superiores (P1 se evalúa aparte)

REGLAS = {
    "HAL-01": "Caso repetido",
    "HAL-02": "Pico por estación",
    "HAL-03": "Categoría en crecimiento",
    "HAL-04": "Sin seguimiento",
    "HAL-05": "Resuelto sin cerrar",
    "HAL-06": "Escalado estancado",
    "HAL-07": "P1 abierto",
    "HAL-08": "Sobrecarga de técnico",
    "HAL-09": "Tickets sin clasificar",
    "HAL-10": "Semáforo en rojo",
    "HAL-11": "Reapertura",
    "HAL-12": "Importación desactualizada",
}
# Reglas que describen la situación actual: se cierran cuando dejan de cumplirse
REGLAS_ACTUALES = ("HAL-04", "HAL-05", "HAL-06", "HAL-07", "HAL-08", "HAL-12")
# Entidades que un usuario de consulta puede ver (las de técnicos y tickets, no)
ENTIDADES_PUBLICAS = ("caso", "estacion", "categoria", "kpi", "importacion")
RECOMENDACION_REPETIDO = "Evaluar Problema en GLPI / runbook / automatización."
SISTEMA = Sesion(usuario_id=0, nombre="Sistema", perfil=seguridad.COORDINADOR, tecnico_id=None)


@dataclass
class Deteccion:
    regla: str
    severidad: str
    entidad_tipo: str
    entidad_valor: str
    periodo: str
    descripcion: str
    datos: dict = field(default_factory=dict)


@dataclass
class ResumenDeteccion:
    nuevos: int = 0
    actualizados: int = 0
    cerrados: int = 0
    altas_nuevas: int = 0


def _iso(fecha: datetime) -> str:
    return fecha.isoformat(sep=" ")


def _tickets(conexion: sqlite3.Connection, sql: str, valores: list) -> list[sqlite3.Row]:
    return conexion.execute(sql, valores).fetchall()


class Detector:
    def __init__(self, conexion: sqlite3.Connection, ahora: datetime | None = None):
        self.conexion = conexion
        self.ahora = ahora or reloj.ahora()
        semana = periodos.semana_de(self.ahora)
        mes = periodos.mes_de(self.ahora)
        self.semanas = [semana.anterior(), semana]
        self.meses = [mes.anterior(), mes]
        self.estaciones = {f["id"]: f["nombre"] for f in conexion.execute("SELECT id, nombre FROM estacion")}
        self.tecnicos = {f["id"]: f["nombre_mostrar"] for f in conexion.execute("SELECT id, nombre_mostrar FROM tecnico")}

    def entero(self, clave: str) -> int:
        return parametros.entero(self.conexion, clave)

    def decimal(self, clave: str) -> float:
        return float(parametros.decimal_opcional(self.conexion, clave))

    # --- HAL-01 ---

    def caso_repetido(self) -> list[Deteccion]:
        inicio = min(self.meses[0].inicio, self.semanas[0].anterior().inicio)
        filas = _tickets(
            self.conexion,
            "SELECT t.id_glpi, t.titulo, t.fecha_apertura, c.estacion_id FROM ticket t "
            "JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
            "WHERE c.estacion_id IS NOT NULL AND t.fecha_apertura >= ?",
            [_iso(inicio)],
        )
        detecciones = []
        for lista, umbral, alta in (
            (self.semanas, self.entero("rep_semana_umbral"), self.entero("rep_semana_alta")),
            (self.meses, self.entero("rep_mes_umbral"), self.entero("rep_mes_alta")),
        ):
            for periodo in lista:
                casos = self._agrupar(filas, periodo)
                previos = self._agrupar(filas, periodo.anterior())
                for (estacion_id, titulo), ids in casos.items():
                    if len(ids) < umbral:
                        continue
                    anterior = len(previos.get((estacion_id, titulo), []))
                    tendencia = "▲" if len(ids) > anterior else "▼" if len(ids) < anterior else "="
                    estacion = self.estaciones.get(estacion_id, str(estacion_id))
                    detecciones.append(Deteccion(
                        "HAL-01", ALTA if len(ids) >= alta else MEDIA, "caso", f"{estacion} | {titulo}",
                        periodo.codigo,
                        f"«{titulo}» se repitió {len(ids)} veces en {estacion} ({periodo.etiqueta}). "
                        f"{RECOMENDACION_REPETIDO}",
                        {"tickets": sorted(ids), "conteo": len(ids), "conteo_anterior": anterior,
                         "tendencia": tendencia, "estacion": estacion, "titulo": titulo},
                    ))
        return detecciones

    @staticmethod
    def _agrupar(filas, periodo) -> dict[tuple, list[int]]:
        grupos: dict[tuple, list[int]] = defaultdict(list)
        for fila in filas:
            if periodo.contiene(datetime.fromisoformat(fila["fecha_apertura"])):
                grupos[(fila["estacion_id"], normalizar_titulo(fila["titulo"]))].append(fila["id_glpi"])
        return grupos

    # --- HAL-02 ---

    def pico_por_estacion(self) -> list[Deteccion]:
        semanas_base = self.entero("pico_semanas")
        k, minimo = self.decimal("pico_desviaciones"), self.entero("pico_minimo")
        detecciones = []
        for semana in self.semanas:
            historia = periodos.ultimos(semana.anterior(), semanas_base)
            filas = _tickets(
                self.conexion,
                "SELECT c.estacion_id, t.id_glpi, t.fecha_apertura FROM ticket t "
                "JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
                "WHERE c.estacion_id IS NOT NULL AND t.fecha_apertura >= ? AND t.fecha_apertura < ?",
                [_iso(historia[0].inicio), _iso(semana.fin)],
            )
            por_estacion: dict[int, list[sqlite3.Row]] = defaultdict(list)
            for fila in filas:
                por_estacion[fila["estacion_id"]].append(fila)
            for estacion_id, lista in por_estacion.items():
                actuales = [f["id_glpi"] for f in lista if semana.contiene(datetime.fromisoformat(f["fecha_apertura"]))]
                conteos = [sum(1 for f in lista if s.contiene(datetime.fromisoformat(f["fecha_apertura"]))) for s in historia]
                media, desviacion = statistics.fmean(conteos), statistics.pstdev(conteos)
                limite = media + k * desviacion
                if len(actuales) >= minimo and len(actuales) > limite:
                    estacion = self.estaciones.get(estacion_id, str(estacion_id))
                    detecciones.append(Deteccion(
                        "HAL-02", ALTA, "estacion", estacion, semana.codigo,
                        f"{estacion} tuvo {len(actuales)} tickets en la {semana.etiqueta}; "
                        f"su media de {semanas_base} semanas es {media:.1f} (límite {limite:.1f}).",
                        {"tickets": sorted(actuales), "conteo": len(actuales), "media": round(media, 2),
                         "desviacion": round(desviacion, 2)},
                    ))
        return detecciones

    # --- HAL-03 ---

    def categoria_en_crecimiento(self) -> list[Deteccion]:
        factor, minimo = self.decimal("crecimiento_factor"), self.entero("crecimiento_minimo")
        detecciones = []
        for mes in self.meses:
            anteriores = periodos.ultimos(mes.anterior(), 3)
            filas = _tickets(
                self.conexion,
                "SELECT c.categoria_codigo, t.id_glpi, t.fecha_apertura FROM ticket t "
                "JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
                "WHERE c.categoria_codigo IS NOT NULL AND t.fecha_apertura >= ? AND t.fecha_apertura < ?",
                [_iso(anteriores[0].inicio), _iso(mes.fin)],
            )
            por_categoria: dict[str, list[sqlite3.Row]] = defaultdict(list)
            for fila in filas:
                por_categoria[fila["categoria_codigo"]].append(fila)
            for codigo, lista in por_categoria.items():
                actuales = [f["id_glpi"] for f in lista if mes.contiene(datetime.fromisoformat(f["fecha_apertura"]))]
                promedio = statistics.fmean(
                    sum(1 for f in lista if m.contiene(datetime.fromisoformat(f["fecha_apertura"]))) for m in anteriores
                )
                if len(actuales) >= minimo and len(actuales) >= factor * promedio:
                    detecciones.append(Deteccion(
                        "HAL-03", MEDIA, "categoria", codigo, mes.codigo,
                        f"La categoría {codigo} tuvo {len(actuales)} tickets en {mes.etiqueta}, frente a un "
                        f"promedio de {promedio:.1f} en los 3 meses anteriores.",
                        {"tickets": sorted(actuales), "conteo": len(actuales), "promedio_3_meses": round(promedio, 2)},
                    ))
        return detecciones

    # --- HAL-04 a HAL-08: situación actual ---

    def sin_seguimiento(self) -> list[Deteccion]:
        umbrales = {p.nivel: parametros.decimal_opcional(self.conexion, f"horas_sin_actualizar_{p.clave}")
                    for p in PRIORIDADES}
        filas = _tickets(self.conexion, "SELECT * FROM ticket WHERE estado_codigo NOT IN ('RESUELTO', 'CERRADO')", [])
        detecciones = []
        for fila in filas:
            umbral = umbrales.get(fila["prioridad_nivel"])
            horas = (self.ahora - datetime.fromisoformat(fila["ultima_actualizacion"])).total_seconds() / 3600
            if umbral is None or horas <= umbral:
                continue
            grave = fila["es_p1"] or fila["prioridad_nivel"] >= PRIORIDAD_ALTA
            detecciones.append(Deteccion(
                "HAL-04", ALTA if grave else MEDIA, "ticket", str(fila["id_glpi"]), ACTUAL,
                f"Ticket {fila['id_glpi']} ({NOMBRE_PRIORIDAD[fila['prioridad_nivel']]}) lleva {horas:.1f} h sin "
                f"actualización; el plazo es {umbral:g} h.",
                {"tickets": [fila["id_glpi"]], "horas": round(horas, 1), "umbral": umbral,
                 "tecnico": self.tecnicos.get(fila["tecnico_principal_id"])},
            ))
        return detecciones

    def resuelto_sin_cerrar(self) -> list[Deteccion]:
        limite = self.ahora - timedelta(days=self.entero("dias_resuelto_sin_cerrar"))
        filas = _tickets(
            self.conexion,
            "SELECT id_glpi, tecnico_principal_id FROM ticket WHERE estado_codigo = 'RESUELTO' AND fecha_solucion < ?",
            [_iso(limite)],
        )
        por_tecnico: dict[int | None, list[int]] = defaultdict(list)
        for fila in filas:
            por_tecnico[fila["tecnico_principal_id"]].append(fila["id_glpi"])
        return [
            Deteccion(
                "HAL-05", BAJA, "tecnico", self.tecnicos.get(tecnico, "Sin técnico"), ACTUAL,
                f"{self.tecnicos.get(tecnico, 'Sin técnico')} tiene {len(ids)} ticket(s) resueltos sin cerrar "
                "(el cierre depende del visto bueno del autor).",
                {"tickets": sorted(ids), "conteo": len(ids)},
            )
            for tecnico, ids in por_tecnico.items()
        ]

    def escalado_estancado(self) -> list[Deteccion]:
        media, alta = self.entero("dias_escalado_alerta"), self.entero("dias_escalado_alta")
        filas = _tickets(
            self.conexion,
            "SELECT t.id_glpi, (SELECT MAX(e.fecha_evento) FROM ticket_evento e WHERE e.ticket_id = t.id_glpi "
            f"AND e.tipo = '{ev.ESCALAMIENTO}') AS desde FROM ticket t WHERE t.estado_codigo = 'ESCALADO'",
            [],
        )
        detecciones = []
        for fila in filas:
            if fila["desde"] is None:
                continue
            dias = (self.ahora - datetime.fromisoformat(fila["desde"])).total_seconds() / 86400
            if dias <= media:
                continue
            detecciones.append(Deteccion(
                "HAL-06", ALTA if dias > alta else MEDIA, "ticket", str(fila["id_glpi"]), ACTUAL,
                f"Ticket {fila['id_glpi']} lleva {dias:.1f} días escalado.",
                {"tickets": [fila["id_glpi"]], "dias": round(dias, 1)},
            ))
        return detecciones

    def p1_abierto(self) -> list[Deteccion]:
        filas = _tickets(
            self.conexion,
            "SELECT id_glpi, titulo FROM ticket WHERE es_p1 = 1 AND estado_codigo NOT IN ('RESUELTO', 'CERRADO')",
            [],
        )
        return [
            Deteccion("HAL-07", ALTA, "ticket", str(f["id_glpi"]), ACTUAL,
                      f"P1 abierto: ticket {f['id_glpi']} «{f['titulo']}».", {"tickets": [f["id_glpi"]]})
            for f in filas
        ]

    def sobrecarga(self) -> list[Deteccion]:
        factor = self.decimal("sobrecarga_factor_mediana")
        filas = _tickets(
            self.conexion,
            "SELECT k.id, k.nombre_mostrar, (SELECT COUNT(*) FROM ticket t WHERE t.tecnico_principal_id = k.id "
            "AND t.estado_codigo NOT IN ('RESUELTO', 'CERRADO')) AS abiertos FROM tecnico k WHERE k.activo = 1",
            [],
        )
        if len(filas) < 3:  # con menos de 3 técnicos la comparación con el equipo no tiene sentido
            return []
        conteos = [f["abiertos"] for f in filas]
        p90, mediana = float(np.percentile(conteos, 90)), statistics.median(conteos)
        return [
            Deteccion(
                "HAL-08", MEDIA, "tecnico", f["nombre_mostrar"], ACTUAL,
                f"{f['nombre_mostrar']} tiene {f['abiertos']} tickets abiertos; el P90 del equipo es "
                f"{p90:.1f} y la mediana {mediana:g}.",
                {"abiertos": f["abiertos"], "p90": round(p90, 2), "mediana": mediana},
            )
            for f in filas if f["abiertos"] > p90 and f["abiertos"] > factor * mediana
        ]

    # --- HAL-09 a HAL-12 ---

    def sin_clasificar(self) -> list[Deteccion]:
        detecciones = []
        for semana in self.semanas:
            filas = _tickets(
                self.conexion,
                "SELECT t.id_glpi, t.tecnico_principal_id FROM ticket t "
                "LEFT JOIN ticket_clasificacion c ON c.ticket_id = t.id_glpi "
                "WHERE t.fecha_solucion >= ? AND t.fecha_solucion < ? AND (c.ticket_id IS NULL OR "
                "c.estacion_id IS NULL OR c.categoria_codigo IS NULL OR c.causa_codigo IS NULL "
                "OR c.tipo_solucion_codigo IS NULL)",
                [_iso(semana.inicio), _iso(semana.fin)],
            )
            por_tecnico: dict[int | None, list[int]] = defaultdict(list)
            for fila in filas:
                por_tecnico[fila["tecnico_principal_id"]].append(fila["id_glpi"])
            for tecnico, ids in por_tecnico.items():
                nombre = self.tecnicos.get(tecnico, "Sin técnico")
                detecciones.append(Deteccion(
                    "HAL-09", BAJA, "tecnico", nombre, semana.codigo,
                    f"{len(ids)} ticket(s) resueltos de {nombre} en la {semana.etiqueta} sin clasificar por completo "
                    "(estación, categoría, causa o tipo de solución).",
                    {"tickets": sorted(ids), "conteo": len(ids)},
                ))
        return detecciones

    def semaforo_en_rojo(self) -> list[Deteccion]:
        calc = CalculadoraKPI(self.conexion, SISTEMA, self.ahora)
        detecciones = []
        for mes in self.meses:
            for codigo, definicion in calc.definiciones.items():
                if not definicion["critico"]:
                    continue
                resultado = calc.calcular(codigo, mes, comparar=False)
                if resultado.semaforo == semaforo.ROJO:
                    detecciones.append(Deteccion(
                        "HAL-10", ALTA, "kpi", codigo, mes.codigo,
                        f"{codigo} {resultado.nombre} está en rojo en {mes.etiqueta}: {resultado.valor:g} {resultado.unidad}.",
                        {"valor": resultado.valor, "unidad": resultado.unidad},
                    ))
        return detecciones

    def reapertura(self) -> list[Deteccion]:
        filas = _tickets(
            self.conexion,
            f"SELECT ticket_id, fecha_evento FROM ticket_evento WHERE tipo = '{ev.REAPERTURA}' AND fecha_evento >= ?",
            [_iso(self.meses[0].inicio)],
        )
        return [
            Deteccion("HAL-11", MEDIA, "ticket", str(f["ticket_id"]), f["fecha_evento"][:10],
                      f"El ticket {f['ticket_id']} se reabrió el {f['fecha_evento'][:16]}.",
                      {"tickets": [f["ticket_id"]]})
            for f in filas
        ]

    def importacion_desactualizada(self) -> list[Deteccion]:
        ultima = carga.ultima_importacion(self.conexion)
        dias = self.entero("dias_importacion_desactualizada")
        if ultima is not None and (self.ahora - ultima).days < dias:
            return []
        texto = "No hay importaciones." if ultima is None else f"La última importación es del {ultima:%d/%m/%Y %H:%M}."
        return [Deteccion("HAL-12", MEDIA, "importacion", "ultima", ACTUAL,
                          f"{texto} Importe una exportación reciente de GLPI.", {})]

    def todas(self) -> list[Deteccion]:
        detecciones = []
        for regla in (self.caso_repetido, self.pico_por_estacion, self.categoria_en_crecimiento,
                      self.sin_seguimiento, self.resuelto_sin_cerrar, self.escalado_estancado, self.p1_abierto,
                      self.sobrecarga, self.sin_clasificar, self.semaforo_en_rojo, self.reapertura,
                      self.importacion_desactualizada):
            detecciones += regla()
        return detecciones


def detectar(conexion: sqlite3.Connection, ahora: datetime | None = None) -> ResumenDeteccion:
    """Ejecuta todas las reglas y guarda los hallazgos sin duplicarlos."""
    detector = Detector(conexion, ahora)
    detecciones = detector.todas()
    ahora_iso = _iso(detector.ahora)
    resumen = ResumenDeteccion()
    vistos = set()
    with conexion:
        for d in detecciones:
            clave = (d.regla, d.entidad_tipo, d.entidad_valor, d.periodo)
            if clave in vistos:
                continue
            vistos.add(clave)
            datos = json.dumps(d.datos, ensure_ascii=False)
            fila = conexion.execute(
                "SELECT id, estado FROM hallazgo WHERE regla = ? AND entidad_tipo = ? AND entidad_valor = ? AND periodo = ?",
                clave,
            ).fetchone()
            if fila is None:
                conexion.execute(
                    "INSERT INTO hallazgo (regla, severidad, entidad_tipo, entidad_valor, periodo, descripcion, "
                    "datos_json, detectado_en, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (d.regla, d.severidad, d.entidad_tipo, d.entidad_valor, d.periodo, d.descripcion, datos,
                     ahora_iso, ahora_iso),
                )
                resumen.nuevos += 1
                resumen.altas_nuevas += d.severidad == ALTA
            else:
                # Un hallazgo cerrado que vuelve a aparecer se reabre; los revisados y descartados se respetan
                estado = NUEVO if fila["estado"] == CERRADO else fila["estado"]
                conexion.execute(
                    "UPDATE hallazgo SET severidad = ?, descripcion = ?, datos_json = ?, actualizado_en = ?, estado = ? "
                    "WHERE id = ?",
                    (d.severidad, d.descripcion, datos, ahora_iso, estado, fila["id"]),
                )
                resumen.actualizados += 1
        marcas = ", ".join("?" * len(REGLAS_ACTUALES))
        for fila in conexion.execute(
            f"SELECT id, regla, entidad_tipo, entidad_valor, periodo FROM hallazgo WHERE periodo = ? "
            f"AND regla IN ({marcas}) AND estado <> ?",
            (ACTUAL, *REGLAS_ACTUALES, CERRADO),
        ).fetchall():
            if (fila["regla"], fila["entidad_tipo"], fila["entidad_valor"], fila["periodo"]) not in vistos:
                conexion.execute("UPDATE hallazgo SET estado = ?, actualizado_en = ? WHERE id = ?",
                                 (CERRADO, ahora_iso, fila["id"]))
                resumen.cerrados += 1
    log.info("Hallazgos: %d nuevos, %d actualizados, %d cerrados", resumen.nuevos, resumen.actualizados, resumen.cerrados)
    return resumen


# --- Consulta y revisión (PAN-09) ---

COLUMNAS = ("ID", "Regla", "Severidad", "Estado", "Entidad", "Período", "Descripción", "Tickets", "Detectado",
            "Actualizado", "Comentario")
ORDEN_SEVERIDAD = {ALTA: 0, MEDIA: 1, BAJA: 2}


def listar(
    conexion: sqlite3.Connection, sesion: Sesion, estados: tuple[str, ...] = (NUEVO, REVISADO),
    severidades: tuple[str, ...] = (), reglas: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Hallazgos visibles por la sesión. Consulta: sin los de técnicos ni tickets individuales."""
    condiciones, valores = [], []
    for columna, lista in (("estado", estados), ("severidad", severidades), ("regla", reglas)):
        if lista:
            condiciones.append(f"{columna} IN ({', '.join('?' * len(lista))})")
            valores.extend(lista)
    if not sesion.es_coordinador:
        condiciones.append(f"entidad_tipo IN ({', '.join('?' * len(ENTIDADES_PUBLICAS))})")
        valores.extend(ENTIDADES_PUBLICAS)
    donde = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    filas = conexion.execute(f"SELECT * FROM hallazgo {donde}", valores).fetchall()
    # Primero los más graves; dentro de cada severidad, los más recientes
    filas.sort(key=lambda f: (ORDEN_SEVERIDAD[f["severidad"]], -datetime.fromisoformat(f["actualizado_en"]).timestamp()))
    return pd.DataFrame(
        [
            {
                "ID": f["id"], "Regla": f"{f['regla']} {REGLAS[f['regla']]}", "Severidad": f["severidad"],
                "Estado": f["estado"], "Entidad": f["entidad_valor"], "Período": f["periodo"],
                "Descripción": f["descripcion"],
                "Tickets": ", ".join(map(str, json.loads(f["datos_json"]).get("tickets", []))),
                "Detectado": f["detectado_en"][:16], "Actualizado": f["actualizado_en"][:16],
                "Comentario": f["comentario"],
            }
            for f in filas
        ],
        columns=list(COLUMNAS),
    )


def conteo_nuevos(conexion: sqlite3.Connection, sesion: Sesion) -> dict[str, int]:
    """Hallazgos NUEVOS por severidad, para el dashboard y la campana."""
    tabla = listar(conexion, sesion, estados=(NUEVO,))
    return {sev: int((tabla["Severidad"] == sev).sum()) for sev in (ALTA, MEDIA, BAJA)}


def revisar(conexion: sqlite3.Connection, sesion: Sesion, hallazgo_id: int, estado: str, comentario: str) -> None:
    """Marca un hallazgo como revisado o descartado, con comentario e historial."""
    seguridad.exigir_coordinador(sesion)
    if estado not in (REVISADO, DESCARTADO, NUEVO):
        raise ErrorValidacion("El estado debe ser Revisado, Descartado o Nuevo.")
    if estado == DESCARTADO and not comentario.strip():
        raise ErrorValidacion("Explique en el comentario por qué se descarta el hallazgo.")
    fila = conexion.execute("SELECT estado FROM hallazgo WHERE id = ?", (hallazgo_id,)).fetchone()
    if fila is None:
        raise ErrorValidacion("El hallazgo no existe.")
    with conexion:
        conexion.execute(
            "UPDATE hallazgo SET estado = ?, comentario = ?, revisado_por = ? WHERE id = ?",
            (estado, comentario.strip() or None, sesion.usuario_id, hallazgo_id),
        )
        historial.registrar(conexion, entidad="hallazgo", entidad_id=hallazgo_id, accion="REVISAR",
                            usuario_id=sesion.usuario_id, campo="estado", valor_anterior=fila["estado"],
                            valor_nuevo=estado, nota=comentario.strip() or None)


def tickets_de(conexion: sqlite3.Connection, hallazgo_id: int) -> list[int]:
    fila = conexion.execute("SELECT datos_json FROM hallazgo WHERE id = ?", (hallazgo_id,)).fetchone()
    return json.loads(fila[0]).get("tickets", []) if fila else []
