"""Evaluación de la calidad de documentación (spec 07: CAL-01, CAL-02, CAL-03).

- CAL-01: se evalúan los 12 criterios generales («Todos») más los del tipo de caso.
- CAL-02: los criterios «Auto» y «Semi» se precalifican con reglas sobre el ticket,
  su clasificación, sus eventos y sus seguimientos. G-11 (datos sensibles) nunca se
  marca «cumple» automáticamente. Corregir un resultado automático exige una nota y
  queda como AUTO_CORREGIDO.
- CAL-03: % = cumple / (cumple + no cumple); los «no aplica» no cuentan. Un criterio
  crítico incumplido hace «No conforme» al ticket, sin importar el porcentaje.
Una sola evaluación vigente por ticket; las anteriores se conservan con su versión.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from core import historial, parametros, reloj, seguridad
from core.analisis import calendario
from core.dominio import CRITICO_P1, NOMBRE_TIPO_CASO, TIPOS_CASO
from core.errores import ErrorPermiso, ErrorValidacion
from core.importacion import eventos as ev
from core.seguridad import Sesion

CUMPLE, NO_CUMPLE, NO_APLICA = "C", "N", "NA"
MANUAL, AUTO, AUTO_CORREGIDO = "MANUAL", "AUTO", "AUTO_CORREGIDO"
CONFORME, POR_MEJORAR, NO_CONFORME = "CONFORME", "POR_MEJORAR", "NO_CONFORME"
NOMBRE_RESULTADO = {CONFORME: "✔ Conforme", POR_MEJORAR: "▲ Por mejorar", NO_CONFORME: "✖ No conforme"}
APLICA_A = {  # tipo de caso → valor de la columna aplica_a del catálogo de criterios
    "GESTION": "Gestión", "ESCALAMIENTO": "Escalamiento", "SOLICITUD": "Solicitud", "CRITICO_P1": "Crítico P1",
    "ESPERA_EXTERNA": "En espera externa", "CAMBIO": "Cambio/despliegue", "ACTIVIDAD": "Actividad programada",
}
_HORA = re.compile(r"\d{1,2}:\d{2}")
_CAUSA = re.compile(r"^\s*CAUSA:\s*CAU-\d{2}", re.IGNORECASE)
_SENSIBLE = re.compile(r"contraseña|password|clave:|pwd", re.IGNORECASE)
PRIORIDAD_ALTA = 4
TURNO_HORAS = 8  # G-10: «resuelto hace menos de 1 turno»


@dataclass(frozen=True)
class Precalificacion:
    resultado: str
    nota: str


@dataclass(frozen=True)
class Puntaje:
    porcentaje: float | None
    criticos_fallidos: int
    resultado: str


# --- CAL-01: criterios que aplican ---

def criterios_para(conexion: sqlite3.Connection, tipo_caso: str) -> list[sqlite3.Row]:
    """Los criterios generales más los del tipo de caso, en el orden del catálogo."""
    if tipo_caso not in APLICA_A:
        raise ErrorValidacion("Tipo de caso desconocido.")
    return conexion.execute(
        "SELECT * FROM criterio_calidad WHERE activo = 1 AND aplica_a IN ('Todos', ?) "
        "ORDER BY aplica_a <> 'Todos', rowid",
        (APLICA_A[tipo_caso],),
    ).fetchall()


# --- CAL-03: puntaje ---

def calcular_puntaje(resultados: dict[str, str], criticos: set[str], umbral_conforme: float,
                     umbral_por_mejorar: float) -> Puntaje:
    cumple = sum(1 for r in resultados.values() if r == CUMPLE)
    no_cumple = sum(1 for r in resultados.values() if r == NO_CUMPLE)
    fallidos = sum(1 for c, r in resultados.items() if r == NO_CUMPLE and c in criticos)
    porcentaje = round(cumple / (cumple + no_cumple) * 100, 2) if cumple + no_cumple else None
    if fallidos == 0 and porcentaje is not None and porcentaje >= umbral_conforme:
        resultado = CONFORME
    elif fallidos == 0 and porcentaje is not None and porcentaje >= umbral_por_mejorar:
        resultado = POR_MEJORAR
    else:
        resultado = NO_CONFORME
    return Puntaje(porcentaje, fallidos, resultado)


def puntaje_con_parametros(conexion: sqlite3.Connection, resultados: dict[str, str]) -> Puntaje:
    criticos = {f[0] for f in conexion.execute("SELECT id FROM criterio_calidad WHERE critico = 1")}
    return calcular_puntaje(resultados, criticos, parametros.decimal_opcional(conexion, "umbral_conforme") or 90,
                            parametros.decimal_opcional(conexion, "umbral_por_mejorar") or 70)


# --- CAL-02: precalificación ---

def _campo(contenido: str, campo: str) -> str:
    """Texto que sigue a «Campo:» en la misma línea (vacío si no está)."""
    coincidencia = re.search(rf"{re.escape(campo)}\s*(.*)", contenido)
    return coincidencia.group(1).strip() if coincidencia else ""


def _con_campos(notas, etiqueta: str, campos: tuple[str, ...]) -> bool | None:
    """True si alguna nota con la etiqueta tiene todos los campos; None si no hay notas con esa etiqueta."""
    candidatas = [n for n in notas if n["etiqueta"] == etiqueta]
    if not candidatas:
        return None
    return any(all(_campo(n["contenido"], c) for c in campos) for n in candidatas)


def _intervalo_maximo(fechas: list[datetime]) -> timedelta:
    fechas = sorted(fechas)
    return max((b - a for a, b in zip(fechas, fechas[1:])), default=timedelta(0))


class Precalificador:
    def __init__(self, conexion: sqlite3.Connection, ticket_id: int, ahora: datetime | None = None):
        self.conexion = conexion
        self.ahora = ahora or reloj.ahora()
        self.ticket = conexion.execute("SELECT * FROM ticket WHERE id_glpi = ?", (ticket_id,)).fetchone()
        if self.ticket is None:
            raise ErrorValidacion(f"El ticket {ticket_id} no existe.")
        self.clasificacion = conexion.execute(
            "SELECT * FROM ticket_clasificacion WHERE ticket_id = ?", (ticket_id,)).fetchone()
        self.notas = [dict(f) | {"fecha": datetime.fromisoformat(f["fecha"])} for f in conexion.execute(
            "SELECT * FROM seguimiento WHERE ticket_id = ? ORDER BY fecha, id", (ticket_id,))]
        self.eventos = {f["tipo"] for f in conexion.execute(
            "SELECT tipo FROM ticket_evento WHERE ticket_id = ?", (ticket_id,))}
        self.solucion = next((n for n in reversed(self.notas) if n["tipo"] == "SOLUCION"), None)
        nivel = self.ticket["prioridad_nivel"]
        p = lambda clave, defecto: parametros.decimal_opcional(conexion, clave) or defecto  # noqa: E731
        if self.ticket["es_p1"]:
            self.umbral = timedelta(minutes=p("umbral_p1_minutos", 60))
        elif nivel >= PRIORIDAD_ALTA:
            self.umbral = timedelta(hours=p("umbral_nota_alta_horas", 4))
        else:
            self.umbral = timedelta(hours=p("umbral_nota_normal_horas", 24))
        self.umbral_escalado = timedelta(hours=p("umbral_nota_alta_horas", 4) if nivel >= PRIORIDAD_ALTA
                                         else p("umbral_nota_normal_horas", 24))
        self.umbral_p1 = timedelta(minutes=p("umbral_p1_minutos", 60))
        self.umbral_recordatorio = timedelta(hours=p("umbral_recordatorio_horas", 26))

    @staticmethod
    def _si(condicion: bool | None, nota_si: str, nota_no: str, sin_datos: str | None = None) -> Precalificacion | None:
        if condicion is None:
            return Precalificacion(NO_APLICA, sin_datos) if sin_datos else None
        return Precalificacion(CUMPLE if condicion else NO_CUMPLE, nota_si if condicion else nota_no)

    # Reglas que usan solo el ticket, su clasificación y sus eventos
    def g02(self):
        c = self.clasificacion
        return self._si(bool(c and c["estacion_id"] and c["categoria_codigo"]),
                        "Estación y categoría asignadas.", "Falta la estación o la categoría en la clasificación.")

    def g07(self):
        if self.ticket["estado_codigo"] not in ("RESUELTO", "CERRADO"):
            return Precalificacion(NO_APLICA, "El ticket todavía no está resuelto.")
        c = self.clasificacion
        clasificada = bool(c and c["tipo_solucion_codigo"] and c["causa_codigo"])
        con_causa = self.solucion is not None and bool(_CAUSA.match(self.solucion["contenido"]))
        return self._si(clasificada or con_causa, "Tiene tipo de solución y CAUSA.",
                        "Falta el tipo de solución o la CAUSA (CAUSA: CAU-xx | detalle).")

    def g10(self):
        estado = self.ticket["estado_codigo"]
        if estado == "CERRADO":
            return Precalificacion(CUMPLE, "El ticket está cerrado.")
        if estado == "RESUELTO" and self.ticket["fecha_solucion"]:
            reciente = self.ahora - datetime.fromisoformat(self.ticket["fecha_solucion"]) < timedelta(hours=TURNO_HORAS)
            return self._si(reciente, "Resuelto hace menos de un turno.", "Resuelto y sin cierre formal.")
        return Precalificacion(NO_APLICA, "El ticket sigue abierto.")

    def e03(self):
        return self._si(ev.ESCALAMIENTO in self.eventos, "Se detectó el escalamiento (estado Escalado).",
                        "No se detectó el paso por el estado Escalado.")

    # Reglas que necesitan seguimientos
    def g01(self):
        return self._si(_con_campos(self.notas, "APERTURA", ("Estación:", "Aplicación:", "Síntoma:", "Impacto:")),
                        "[APERTURA] con los campos completos.", "[APERTURA] con campos vacíos.")\
            or Precalificacion(NO_CUMPLE, "No hay nota [APERTURA].")

    def g03(self):
        notas = [n for n in self.notas if n["etiqueta"] in ("DIAG", "AVANCE")]
        if not notas:
            return Precalificacion(NO_CUMPLE, "No hay notas [DIAG] ni [AVANCE].")
        completas = all(_campo(n["contenido"], "Hice:") and _campo(n["contenido"], "Sigue:") for n in notas)
        return self._si(completas, "Notas con Hice / Sigue.", "Alguna nota sin «Hice:» o «Sigue:».")

    def g04(self):
        con_sigue = [n for n in self.notas if _campo(n["contenido"], "Sigue:")]
        if not con_sigue:
            return Precalificacion(NO_CUMPLE, "Ninguna nota indica «Sigue:».")
        return self._si(all(_HORA.search(_campo(n["contenido"], "Sigue:")) for n in con_sigue),
                        "Cada «Sigue:» tiene hora.", "Algún «Sigue:» sin hora hh:mm.")

    def g05(self):
        apertura = datetime.fromisoformat(self.ticket["fecha_apertura"])
        fin = self.solucion["fecha"] if self.solucion else self.ahora
        fechas = [apertura] + [n["fecha"] for n in self.notas if n["fecha"] <= fin] + [fin]
        # No cuenta el tiempo en espera externa: intervalos que empiezan en [ESPERA] o [RECORDATORIO]
        en_espera = {n["fecha"] for n in self.notas if n["etiqueta"] in ("ESPERA", "RECORDATORIO")}
        fechas = sorted(set(fechas))
        maximo = max((b - a for a, b in zip(fechas, fechas[1:]) if a not in en_espera), default=timedelta(0))
        horas = maximo.total_seconds() / 3600
        return self._si(maximo <= self.umbral, f"Intervalo máximo entre notas: {horas:.1f} h.",
                        f"Intervalo máximo entre notas: {horas:.1f} h (máximo {self.umbral.total_seconds() / 3600:g} h).")

    def g06(self):
        tareas = [n for n in self.notas if n["tipo"] == "TAREA"]
        if not tareas:
            return Precalificacion(NO_APLICA, "No hay tareas.")
        return self._si(all(n["categoria_tarea"] and (n["duracion_min"] or 0) > 0 for n in tareas),
                        "Todas las tareas con categoría y duración.", "Alguna tarea sin categoría o sin duración.")

    def g08(self):
        if self.solucion is None:
            return Precalificacion(NO_APLICA, "No hay nota de solución.")
        return self._si(len(_campo(self.solucion["contenido"], "Verificación:")) > 10,
                        "La solución indica cómo se verificó.", "La solución no tiene «Verificación:» completa.")

    def g11(self):
        encontradas = [n for n in self.notas if _SENSIBLE.search(n["contenido"])]
        if encontradas:
            return Precalificacion(NO_CUMPLE, "Revisar: posible contraseña o dato sensible en una nota "
                                              f"del {encontradas[0]['fecha']:%d/%m %H:%M}.")
        return None  # nunca se marca «cumple» automáticamente

    def ge01(self):
        diag = [n for n in self.notas if n["etiqueta"] == "DIAG" or (n["tipo"] == "TAREA" and n["categoria_tarea"] == "DIAG")]
        return self._si(any(_campo(n["contenido"], "Hice:") and _campo(n["contenido"], "Encontré:") for n in diag),
                        "Diagnóstico con pruebas y resultado.", "Falta un [DIAG] con «Hice:» y «Encontré:».")

    def ge02(self):
        if self.solucion is None:
            return Precalificacion(NO_APLICA, "No hay nota de solución.")
        return self._si(bool(_HORA.search(_campo(self.solucion["contenido"], "Verificación:"))),
                        "La verificación indica la hora.", "La verificación no indica la hora hh:mm.")

    def e01(self):
        return self._si(_con_campos(self.notas, "ESC", ("Motivo:", "Pruebas:", "Se solicita:")),
                        "[ESC] completo.", "[ESC] sin Motivo, Pruebas o Se solicita.") \
            or Precalificacion(NO_CUMPLE, "No hay nota [ESC].")

    def e04(self):
        return self._si(_con_campos(self.notas, "ESC", ("Ref.:",)), "[ESC] con referencia externa.",
                        "[ESC] sin «Ref.:».") or Precalificacion(NO_CUMPLE, "No hay nota [ESC].")

    def e05(self):
        marcas = [n["fecha"] for n in self.notas if n["etiqueta"] in ("ESC", "SEG-ESC", "RETORNO")]
        if not any(n["etiqueta"] == "ESC" for n in self.notas):
            return Precalificacion(NO_CUMPLE, "No hay nota [ESC].")
        maximo = _intervalo_maximo(marcas)
        horas = maximo.total_seconds() / 3600
        return self._si(maximo <= self.umbral_escalado, f"Seguimiento al área cada {horas:.1f} h como máximo.",
                        f"Hubo {horas:.1f} h sin [SEG-ESC] (máximo {self.umbral_escalado.total_seconds() / 3600:g} h).")

    def e06(self):
        retorno = next((n for n in self.notas if n["etiqueta"] == "RETORNO"), None)
        if retorno is None:
            return Precalificacion(NO_CUMPLE, "No hay nota [RETORNO].")
        return self._si(self.solucion is None or retorno["fecha"] <= self.solucion["fecha"],
                        "[RETORNO] antes de la solución.", "[RETORNO] posterior a la solución.")

    def s01(self):
        return self._si(_con_campos(self.notas, "REQ", ("Aprobación:",)), "[REQ] con aprobación.",
                        "[REQ] sin «Aprobación:».") or Precalificacion(NO_CUMPLE, "No hay nota [REQ].")

    def s02(self):
        return self._si(_con_campos(self.notas, "EJEC", ("Evidencia:",)), "[EJEC] con evidencia.",
                        "[EJEC] sin «Evidencia:».") or Precalificacion(NO_CUMPLE, "No hay nota [EJEC].")

    def p01(self):
        return self._si(_con_campos(self.notas, "P1-INICIO", ("Detección:", "Aviso:")), "[P1-INICIO] completo.",
                        "[P1-INICIO] sin Detección o Aviso.") or Precalificacion(NO_CUMPLE, "No hay nota [P1-INICIO].")

    def p02(self):
        restablecido = next((n["fecha"] for n in self.notas if n["etiqueta"] == "P1-RESTABLECIDO"), None)
        fechas = [n["fecha"] for n in self.notas if n["etiqueta"] in ("P1-INICIO", "P1-ACT", "P1-RESTABLECIDO")
                  and (restablecido is None or n["fecha"] <= restablecido)]
        if not fechas:
            return Precalificacion(NO_CUMPLE, "No hay notas [P1-INICIO] ni [P1-ACT].")
        maximo = _intervalo_maximo(fechas)
        return self._si(maximo <= self.umbral_p1, f"Actualizaciones P1 cada {maximo.total_seconds() / 60:.0f} min como máximo.",
                        f"Hubo {maximo.total_seconds() / 60:.0f} min sin [P1-ACT] (máximo {self.umbral_p1.total_seconds() / 60:g}).")

    def p03(self):
        return self._si(_con_campos(self.notas, "P1-CIERRE", ("Impacto:", "CAUSA:")), "[P1-CIERRE] completo.",
                        "[P1-CIERRE] sin Impacto o CAUSA.") or Precalificacion(NO_CUMPLE, "No hay nota [P1-CIERRE].")

    def w01(self):
        return self._si(_con_campos(self.notas, "ESPERA", ("Qué:", "Recordatorio:")), "[ESPERA] completa.",
                        "[ESPERA] sin Qué o Recordatorio.") or Precalificacion(NO_CUMPLE, "No hay nota [ESPERA].")

    def w02(self):
        espera = next((n["fecha"] for n in self.notas if n["etiqueta"] == "ESPERA"), None)
        if espera is None:
            return Precalificacion(NO_CUMPLE, "No hay nota [ESPERA].")
        fechas = [espera] + [n["fecha"] for n in self.notas if n["etiqueta"] == "RECORDATORIO" and n["fecha"] > espera]
        if len(fechas) == 1:
            return Precalificacion(NO_CUMPLE, "No hay recordatorios después de [ESPERA].")
        maximo = _intervalo_maximo(fechas)
        return self._si(maximo <= self.umbral_recordatorio, "Recordatorios a tiempo.",
                        f"Hubo {maximo.total_seconds() / 3600:.1f} h entre recordatorios.")

    def c01(self):
        return self._si(_con_campos(self.notas, "CAMBIO-PLAN", ("Aprobó:", "Versión:", "Reversión:")),
                        "[CAMBIO-PLAN] completo.", "[CAMBIO-PLAN] sin Aprobó, Versión o Reversión.") \
            or Precalificacion(NO_CUMPLE, "No hay nota [CAMBIO-PLAN].")

    def c02(self):
        ejecucion = next((n["fecha"] for n in self.notas if n["etiqueta"] == "CAMBIO-EJEC"), None)
        if ejecucion is None:
            return Precalificacion(NO_CUMPLE, "No hay nota [CAMBIO-EJEC].")
        festivos = calendario.festivos_guardados(self.conexion)
        dentro = ejecucion.weekday() <= 3 and ejecucion.hour < 16 and ejecucion.date() not in festivos
        return self._si(dentro, "Ejecutado dentro de la ventana (lun–jue antes de 16:00).",
                        f"Ejecutado fuera de la ventana: {ejecucion:%A %d/%m %H:%M}.")

    def c03(self):
        return self._si(_con_campos(self.notas, "CAMBIO-EJEC", ("Verificación:",)), "[CAMBIO-EJEC] con verificación.",
                        "[CAMBIO-EJEC] sin «Verificación:».") or Precalificacion(NO_CUMPLE, "No hay nota [CAMBIO-EJEC].")

    def a01(self):
        return self._si(_con_campos(self.notas, "ACT", ("Resultado:",)), "[ACT] con resultado.",
                        "[ACT] sin «Resultado:».") or Precalificacion(NO_CUMPLE, "No hay nota [ACT].")

    def a02(self):
        actividad = [n for n in self.notas if n["etiqueta"] == "ACT" and "hallazgo" in n["contenido"].lower()]
        if not actividad:
            return Precalificacion(NO_APLICA, "La actividad no reporta hallazgos.")
        return self._si(all(re.search(r"#\d+", n["contenido"]) for n in actividad),
                        "El hallazgo referencia un ticket.", "El hallazgo no referencia un ticket (#n.º).")

    SIN_SEGUIMIENTOS = ("G-02", "G-07", "G-10", "E-03")

    def precalificar(self, criterios: list[str]) -> dict[str, Precalificacion]:
        resultado = {}
        for criterio in criterios:
            regla = getattr(self, criterio.lower().replace("-", ""), None)
            if regla is None:
                continue  # criterio manual (G-09, G-12, E-02, P-04, W-03)
            if not self.notas and criterio not in self.SIN_SEGUIMIENTOS:
                continue  # sin seguimientos importados, el resto es manual
            precalificacion = regla()
            if precalificacion is not None:
                resultado[criterio] = precalificacion
        return resultado


def precalificar(conexion: sqlite3.Connection, ticket_id: int, tipo_caso: str,
                 ahora: datetime | None = None) -> dict[str, Precalificacion]:
    """Resultados automáticos de los criterios Auto y Semi que aplican (CAL-02)."""
    criterios = [c["id"] for c in criterios_para(conexion, tipo_caso) if c["automatizable"] in ("Auto", "Semi")]
    return Precalificador(conexion, ticket_id, ahora).precalificar(criterios)


# --- CAL-01: guardar la evaluación ---

def guardar_evaluacion(
    conexion: sqlite3.Connection, sesion: Sesion, ticket_id: int, tipo_caso: str,
    resultados: dict[str, tuple[str, str | None]], retroalimentacion: str = "", ahora: datetime | None = None,
) -> int:
    """Guarda una evaluación nueva y deja la anterior como versión previa.

    `resultados`: criterio → (C / N / NA, nota). El origen (MANUAL, AUTO o
    AUTO_CORREGIDO) se calcula comparando con la precalificación: si el coordinador
    cambió un resultado automático, la nota es obligatoria.
    """
    seguridad.exigir_coordinador(sesion)
    if tipo_caso not in TIPOS_CASO:
        raise ErrorValidacion("Tipo de caso desconocido.")
    ahora = ahora or reloj.ahora()
    aplicables = [c["id"] for c in criterios_para(conexion, tipo_caso)]
    faltan = [c for c in aplicables if c not in resultados]
    if faltan:
        raise ErrorValidacion(f"Falta calificar: {', '.join(faltan)}.")
    sobran = set(resultados) - set(aplicables)
    if sobran:
        raise ErrorValidacion(f"Estos criterios no aplican al tipo de caso: {', '.join(sorted(sobran))}.")
    automaticos = precalificar(conexion, ticket_id, tipo_caso, ahora)
    detalle = []
    for criterio in aplicables:
        valor, nota = resultados[criterio]
        if valor not in (CUMPLE, NO_CUMPLE, NO_APLICA):
            raise ErrorValidacion(f"Resultado inválido para {criterio}.")
        nota = (nota or "").strip() or None
        if criterio in automaticos and automaticos[criterio].resultado != valor:
            if not nota:
                raise ErrorValidacion(f"Explique en la nota por qué corrige el resultado automático de {criterio}.")
            origen = AUTO_CORREGIDO
        elif criterio in automaticos:
            origen, nota = AUTO, nota or automaticos[criterio].nota
        else:
            origen = MANUAL
        detalle.append((criterio, valor, origen, nota))
    puntaje = puntaje_con_parametros(conexion, {c: v for c, v, _, _ in detalle})
    if puntaje.porcentaje is None and puntaje.criticos_fallidos == 0:
        raise ErrorValidacion("Marque al menos un criterio como «cumple» o «no cumple».")
    ticket = conexion.execute("SELECT tipo_caso FROM ticket WHERE id_glpi = ?", (ticket_id,)).fetchone()
    with conexion:
        version = conexion.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM evaluacion WHERE ticket_id = ?", (ticket_id,)).fetchone()[0]
        conexion.execute("UPDATE evaluacion SET vigente = 0 WHERE ticket_id = ?", (ticket_id,))
        cursor = conexion.execute(
            "INSERT INTO evaluacion (ticket_id, tipo_caso, auditor_id, fecha, porcentaje, criticos_fallidos, resultado, "
            "retroalimentacion, version, vigente) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (ticket_id, tipo_caso, sesion.usuario_id, ahora.isoformat(sep=" "), puntaje.porcentaje,
             puntaje.criticos_fallidos, puntaje.resultado, retroalimentacion.strip() or None, version),
        )
        evaluacion_id = cursor.lastrowid
        conexion.executemany(
            "INSERT INTO evaluacion_detalle (evaluacion_id, criterio_id, resultado, origen, nota) VALUES (?, ?, ?, ?, ?)",
            [(evaluacion_id, *fila) for fila in detalle],
        )
        historial.registrar(conexion, entidad="evaluacion", entidad_id=ticket_id, accion="EVALUAR",
                            usuario_id=sesion.usuario_id, campo="version",
                            valor_nuevo=f"v{version}: {puntaje.porcentaje}% {NOMBRE_RESULTADO[puntaje.resultado]}",
                            nota=retroalimentacion.strip() or None)
        for criterio, valor, origen, nota in detalle:
            if origen == AUTO_CORREGIDO:
                historial.registrar(conexion, entidad="evaluacion", entidad_id=ticket_id, accion=AUTO_CORREGIDO,
                                    usuario_id=sesion.usuario_id, campo=criterio,
                                    valor_anterior=automaticos[criterio].resultado, valor_nuevo=valor, nota=nota)
        if ticket["tipo_caso"] != tipo_caso:
            conexion.execute("UPDATE ticket SET tipo_caso = ?, tipo_caso_origen = 'MANUAL' WHERE id_glpi = ?",
                             (tipo_caso, ticket_id))
            historial.registrar(conexion, entidad="ticket", entidad_id=ticket_id, accion="MODIFICAR",
                                usuario_id=sesion.usuario_id, campo="tipo_caso",
                                valor_anterior=NOMBRE_TIPO_CASO[ticket["tipo_caso"]], valor_nuevo=NOMBRE_TIPO_CASO[tipo_caso])
    return evaluacion_id


def evaluacion_vigente(conexion: sqlite3.Connection, sesion: Sesion, ticket_id: int) -> tuple[sqlite3.Row, list] | None:
    """La evaluación vigente y su detalle. Consulta: solo de sus propios tickets."""
    if not sesion.es_coordinador:
        propio = conexion.execute("SELECT tecnico_principal_id FROM ticket WHERE id_glpi = ?", (ticket_id,)).fetchone()
        if propio is None or sesion.tecnico_id is None or propio[0] != sesion.tecnico_id:
            raise ErrorPermiso("Solo puede ver las evaluaciones de sus propios tickets.")
    evaluacion = conexion.execute(
        "SELECT v.*, u.nombre AS auditor FROM evaluacion v LEFT JOIN usuario u ON u.id = v.auditor_id "
        "WHERE v.ticket_id = ? AND v.vigente = 1", (ticket_id,)).fetchone()
    if evaluacion is None:
        return None
    detalle = conexion.execute(
        "SELECT d.*, c.descripcion, c.critico FROM evaluacion_detalle d JOIN criterio_calidad c ON c.id = d.criterio_id "
        "WHERE d.evaluacion_id = ? ORDER BY c.aplica_a <> 'Todos', c.rowid", (evaluacion["id"],)).fetchall()
    return evaluacion, detalle


def tipo_caso_sugerido(conexion: sqlite3.Connection, ticket_id: int) -> str:
    """El tipo del ticket (inferido o corregido); P1 si es de prioridad máxima."""
    fila = conexion.execute("SELECT tipo_caso, es_p1 FROM ticket WHERE id_glpi = ?", (ticket_id,)).fetchone()
    if fila is None:
        raise ErrorValidacion(f"El ticket {ticket_id} no existe.")
    return CRITICO_P1 if fila["es_p1"] and fila["tipo_caso"] == "GESTION" else fila["tipo_caso"]

