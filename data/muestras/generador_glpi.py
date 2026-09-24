"""Generador de exportaciones CSV ficticias de GLPI 9.1.4 (formato IMP-00 de spec 03).

Simula la vida de cada ticket (asignación, escalamientos, esperas, reasignaciones,
solución, reapertura y cierre) y produce una o varias "fotos" del estado de los
tickets en distintas fechas de corte, como si se exportara desde GLPI cada día.
Todos los datos son inventados; nunca se usan datos reales.

Uso:
    .venv\\Scripts\\python data\\muestras\\generador_glpi.py --tickets 300 --cortes 5
    .venv\\Scripts\\python data\\muestras\\generador_glpi.py --tickets 20000 --desde 2021-09-01
"""

import argparse
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from core.dominio import MAPEO_ESTADOS_GLPI, PRIORIDADES  # noqa: E402

ENCABEZADOS = (
    "ID",
    "Título",
    "Entidad",
    "Estado",
    "Autor - Autor",
    "Asignado a: - Técnico",
    "Fecha de Apertura",
    "Última actualización",
    "Prioridad",
    "Ubicación",
)
FORMATO_FECHA = "%d-%m-%Y %H:%M"
CARPETA_SALIDA = Path(__file__).resolve().parent / "generados"

NUEVO = "Nuevo"
ASIGNADO = "En curso (asignada)"
PLANIFICADO = "En curso (planificada)"
ESPERA = "En espera"
ESCALADO = "Escalado"
RESUELTO = "Resueltas"
CERRADO = "Cerrado"
assert {NUEVO, ASIGNADO, PLANIFICADO, ESPERA, ESCALADO, RESUELTO, CERRADO} == set(
    MAPEO_ESTADOS_GLPI
)

TECNICOS = tuple(f"Tecnico {n:02d}" for n in range(1, 10))
ENTIDAD_BASE = "Grupo Demo > Empresa Demo > Seccional Demo > Departamento TI > Soporte OP"
ENTIDAD_OTRA = f"{ENTIDAD_BASE}> OTRO GRUPO"
CLIENTES = ("Cliente A", "Cliente B", "Cliente C")
ASUNTOS = (
    "Falla en aplicación de carril",
    "Consulta sobre reporte",
    "Equipo no responde",
    "Diferencia en conciliación",
    "Solicitud de usuario",
    "Lentitud en el sistema",
    "Error al transmitir información",
    "Ajuste de configuración",
)

# Peso de cada prioridad y horas típicas de trabajo antes de un cambio de estado
_PESO_PRIORIDAD = {"Mayor": 2, "Muy urgente": 8, "Urgente": 20, "Mediana": 45, "Baja": 20, "Muy baja": 5}
_HORAS_BASE = {"Mayor": 1.5, "Muy urgente": 5, "Urgente": 10, "Mediana": 24, "Baja": 48, "Muy baja": 80}
assert set(_PESO_PRIORIDAD) == {p.nombre for p in PRIORIDADES}


@dataclass(frozen=True)
class Cambio:
    """Cambio en la vida de un ticket. Los campos en None no cambian."""

    fecha: datetime
    estado: str | None = None
    tecnicos: tuple[str, ...] | None = None
    prioridad: str | None = None


@dataclass
class TicketFicticio:
    id_glpi: int
    titulo: str
    entidad: str
    autor: str
    ubicacion: str
    apertura: datetime
    cambios: list[Cambio] = field(default_factory=list)  # el primero fija los valores iniciales
    actualizaciones: list[datetime] = field(default_factory=list)  # notas sin cambio de campos

    def foto(self, corte: datetime) -> dict | None:
        """Estado del ticket en la fecha de corte, o None si aún no existía."""
        if self.apertura > corte:
            return None
        estado, tecnicos, prioridad = None, (), None
        ultima = self.apertura
        for cambio in sorted(self.cambios, key=lambda c: c.fecha):
            if cambio.fecha > corte:
                break
            estado = cambio.estado or estado
            tecnicos = cambio.tecnicos if cambio.tecnicos is not None else tecnicos
            prioridad = cambio.prioridad or prioridad
            ultima = max(ultima, cambio.fecha)
        for fecha in self.actualizaciones:
            if fecha <= corte:
                ultima = max(ultima, fecha)
        return {
            "id_glpi": self.id_glpi,
            "titulo": self.titulo,
            "entidad": self.entidad,
            "estado": estado,
            "autor": self.autor,
            "tecnicos": tecnicos,
            "apertura": self.apertura,
            "ultima_actualizacion": ultima,
            "prioridad": prioridad,
            "ubicacion": self.ubicacion,
        }

    def veces_en(self, estado: str) -> int:
        return sum(1 for c in self.cambios if c.estado == estado)


# --- Simulación ---

def _horas(rng: random.Random, media: float) -> timedelta:
    """Duración con distribución log-normal: la mayoría cerca de la media, algunas largas."""
    valor = rng.lognormvariate(math.log(media), 0.8)
    return timedelta(minutes=max(5, round(valor * 60)))


def _otro_tecnico(rng: random.Random, actuales: tuple[str, ...]) -> str:
    return rng.choice([t for t in TECNICOS if t not in actuales])


def _simular(rng: random.Random, ticket: TicketFicticio, prioridad: str) -> None:
    base = _HORAS_BASE[prioridad]
    t = ticket.apertura
    principal = rng.choice(TECNICOS)
    tecnicos = (principal,) if rng.random() < 0.85 else (principal, _otro_tecnico(rng, (principal,)))
    if rng.random() < 0.05:
        # Llega sin asignar y se asigna después
        ticket.cambios.append(Cambio(t, estado=NUEVO, tecnicos=(), prioridad=prioridad))
        t += _horas(rng, 1)
        ticket.cambios.append(Cambio(t, estado=ASIGNADO, tecnicos=tecnicos))
    else:
        ticket.cambios.append(Cambio(t, estado=ASIGNADO, tecnicos=tecnicos, prioridad=prioridad))

    escalamientos = 0
    for _ in range(8):
        t += _horas(rng, base)
        azar = rng.random()
        if escalamientos < 3 and azar < (0.25 if escalamientos == 0 else 0.3):
            escalamientos += 1
            ticket.cambios.append(Cambio(t, estado=ESCALADO))
            t += _horas(rng, base * 2)
            ticket.cambios.append(Cambio(t, estado=ASIGNADO))
        elif azar < 0.45:
            ticket.cambios.append(Cambio(t, estado=ESPERA))
            t += _horas(rng, base)
            ticket.cambios.append(Cambio(t, estado=PLANIFICADO if rng.random() < 0.1 else ASIGNADO))
        else:
            break
    fin_trabajo = t
    ticket.cambios.append(Cambio(t, estado=RESUELTO))

    if rng.random() < 0.06:
        # Reapertura: el autor no aprueba la solución
        t += timedelta(hours=rng.uniform(4, 48))
        ticket.cambios.append(Cambio(t, estado=ASIGNADO))
        t += _horas(rng, base)
        ticket.cambios.append(Cambio(t, estado=RESUELTO))
    if rng.random() < 0.8:
        t += timedelta(hours=rng.uniform(6, 144))
        ticket.cambios.append(Cambio(t, estado=CERRADO))

    duracion = (fin_trabajo - ticket.apertura).total_seconds()
    if rng.random() < 0.1:
        momento = ticket.apertura + timedelta(seconds=rng.uniform(0.1, 0.9) * duracion)
        ticket.cambios.append(Cambio(momento, tecnicos=(_otro_tecnico(rng, tecnicos),)))
    if rng.random() < 0.05:
        momento = ticket.apertura + timedelta(seconds=rng.uniform(0.1, 0.9) * duracion)
        nueva = rng.choice([p.nombre for p in PRIORIDADES if p.nombre != prioridad])
        ticket.cambios.append(Cambio(momento, prioridad=nueva))
    ticket.cambios.sort(key=lambda c: c.fecha)
    ticket.actualizaciones = sorted(
        ticket.apertura + timedelta(seconds=rng.uniform(0, 1) * duracion)
        for _ in range(rng.randint(0, 4))
    )
    if escalamientos:
        ticket.entidad = ENTIDAD_OTRA if rng.random() < 0.3 else ENTIDAD_BASE


def generar_tickets(
    cantidad: int, desde: datetime, hasta: datetime, semilla: int = 42, id_inicial: int = 340_000
) -> list[TicketFicticio]:
    """Tickets con apertura entre desde y hasta, ordenados por apertura."""
    rng = random.Random(semilla)
    segundos = (hasta - desde).total_seconds()
    aperturas = sorted(
        (desde + timedelta(seconds=rng.uniform(0, segundos))).replace(second=0, microsecond=0)
        for _ in range(cantidad)
    )
    prioridades = list(_PESO_PRIORIDAD)
    pesos = list(_PESO_PRIORIDAD.values())
    tickets = []
    id_glpi = id_inicial
    for numero, apertura in enumerate(aperturas, start=1):
        id_glpi += rng.randint(1, 5)
        cliente = rng.choice(CLIENTES)
        ticket = TicketFicticio(
            id_glpi=id_glpi,
            titulo=f"Novedad ficticia {numero:05d} - {rng.choice(ASUNTOS)}",
            entidad=ENTIDAD_BASE,
            autor=f"Autor {rng.randint(1, 60):03d}",
            ubicacion=f"Departamento TI > Filial Demo > {cliente} > Estación {rng.randint(1, 12):02d}",
            apertura=apertura,
        )
        _simular(rng, ticket, rng.choices(prioridades, pesos)[0])
        tickets.append(ticket)
    return tickets


# --- Exportación ---

def filas_en(tickets: list[TicketFicticio], corte: datetime) -> list[dict]:
    """Fotos de los tickets existentes en la fecha de corte."""
    return [foto for ticket in tickets if (foto := ticket.foto(corte)) is not None]


def inyectar_errores(filas: list[dict], cantidad: int, semilla: int = 7) -> list[dict]:
    """Agrega filas con errores de validación (IMP-02), rotando los tipos de error.

    Cada fila con error lleva la clave "error" con el defecto introducido.
    """
    rng = random.Random(semilla)
    defectos = ("fecha_invalida", "id_vacio", "id_no_numerico", "id_duplicado",
                "estado_sin_mapear", "prioridad_sin_mapear")
    resultado = list(filas)
    for numero in range(cantidad):
        defecto = defectos[numero % len(defectos)]
        base = dict(rng.choice(filas))
        base["titulo"] = f"Fila con error ({defecto})"
        base["error"] = defecto
        if defecto == "fecha_invalida":
            base["apertura"] = "31-02-2026 10:00"
        elif defecto == "id_vacio":
            base["id_glpi"] = ""
        elif defecto == "id_no_numerico":
            base["id_glpi"] = "34A 123"
        elif defecto == "estado_sin_mapear":
            base["id_glpi"] = 990_000 + numero
            base["estado"] = "Pendiente de revisión"
        elif defecto == "prioridad_sin_mapear":
            base["id_glpi"] = 990_000 + numero
            base["prioridad"] = "Crítica"
        resultado.append(base)
    return resultado


def formatear_id(id_glpi, separador_miles: str = " ") -> str:
    """346649 → «346 649», como lo exporta GLPI. Los textos se dejan como vienen."""
    if not isinstance(id_glpi, int):
        return str(id_glpi)
    return f"{id_glpi:,}".replace(",", separador_miles)


def _campo(valor) -> str:
    texto = valor.strftime(FORMATO_FECHA) if isinstance(valor, datetime) else str(valor)
    return '"' + texto.replace('"', '""') + '"'


def texto_csv(filas: list[dict], separador_miles: str = " ", semilla: int = 3) -> str:
    """Texto del CSV con el formato de IMP-00: «;», comillas y «;» al final de cada línea."""
    rng = random.Random(semilla)
    lineas = [";".join(_campo(e) for e in ENCABEZADOS) + ";"]
    for fila in filas:
        # GLPI separa los técnicos con saltos de línea; a veces deja líneas vacías
        union = "\n\n" if rng.random() < 0.3 else "\n"
        valores = (
            formatear_id(fila["id_glpi"], separador_miles),
            fila["titulo"],
            fila["entidad"],
            fila["estado"],
            fila["autor"],
            union.join(fila["tecnicos"]),
            fila["apertura"],
            fila["ultima_actualizacion"],
            fila["prioridad"],
            fila["ubicacion"],
        )
        lineas.append(";".join(_campo(v) for v in valores) + ";")
    return "\n".join(lineas) + "\n"


def escribir_csv(
    filas: list[dict], ruta: Path, codificacion: str = "utf-8", separador_miles: str = " "
) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(texto_csv(filas, separador_miles).encode(codificacion))
    return ruta


def cortes_diarios(hasta: datetime, cantidad: int, hora: time = time(7, 0)) -> list[datetime]:
    """Las últimas `cantidad` fechas de corte diarias a la hora dada, terminando en `hasta`."""
    ultimo = datetime.combine(hasta.date(), hora)
    if ultimo > hasta:
        ultimo -= timedelta(days=1)
    return [ultimo - timedelta(days=d) for d in range(cantidad - 1, -1, -1)]


def generar_exportaciones(
    carpeta: Path,
    cantidad: int,
    desde: datetime,
    hasta: datetime,
    cortes: int = 1,
    errores: int = 0,
    semilla: int = 42,
    codificacion: str = "utf-8",
    separador_miles: str = " ",
) -> list[Path]:
    """Escribe un CSV por fecha de corte. Los errores se agregan solo al último."""
    tickets = generar_tickets(cantidad, desde, hasta, semilla)
    fechas = cortes_diarios(hasta, cortes)
    rutas = []
    for numero, corte in enumerate(fechas, start=1):
        filas = filas_en(tickets, corte)
        if numero == len(fechas) and errores:
            filas = inyectar_errores(filas, errores)
        nombre = f"glpi_tickets_{corte:%Y%m%d_%H%M}.csv"
        rutas.append(escribir_csv(filas, carpeta / nombre, codificacion, separador_miles))
    # Seguimientos y tareas hasta el último corte (Fase 3)
    ultimo = fechas[-1]
    rutas.append(escribir_csv_seguimientos(filas_seguimientos(tickets, ultimo, semilla),
                                           carpeta / f"glpi_seguimientos_{ultimo:%Y%m%d_%H%M}.csv", codificacion))
    return rutas


# --- Seguimientos y tareas (Fase 3) ---

ENCABEZADOS_SEGUIMIENTOS = (
    "ID del ticket", "Fecha", "Autor", "Tipo", "Privado", "Contenido", "Categoría de tarea", "Duración",
)
_TIPO_TEXTO = {"SEGUIMIENTO": "Seguimiento", "TAREA": "Tarea", "SOLUCION": "Solución"}


def _nota(fecha, autor, contenido, tipo="SEGUIMIENTO", categoria="", duracion="", privado=False) -> dict:
    return {"fecha": fecha.replace(second=0, microsecond=0), "autor": autor, "tipo": tipo, "contenido": contenido,
            "categoria": categoria, "duracion": duracion, "privado": privado}


def seguimientos_de(ticket: TicketFicticio, semilla: int = 0) -> list[dict]:
    """Notas coherentes con la historia del ticket, con defectos ocasionales para evaluar calidad."""
    rng = random.Random(semilla * 1_000_003 + ticket.id_glpi)
    cambios = sorted(ticket.cambios, key=lambda c: c.fecha)
    prioridad = cambios[0].prioridad
    tecnicos = next((c.tecnicos for c in cambios if c.tecnicos), ()) or ("Tecnico 01",)
    autor = tecnicos[0]
    es_p1 = prioridad == "Mayor"
    intervalo = timedelta(minutes=55) if es_p1 else timedelta(hours=3.5) if prioridad in ("Urgente", "Muy urgente") \
        else timedelta(hours=20)
    hhmm = lambda f: f"{f:%H:%M}"  # noqa: E731
    notas = []
    t = ticket.apertura + timedelta(minutes=rng.randint(3, 15))
    sintoma = "" if rng.random() < 0.1 else "Síntoma:     la aplicación muestra «Error de conexión»\n"
    notas.append(_nota(t, autor, f"[APERTURA] {hhmm(t)}\nReporta:     operador por llamada\nEstación:    Estación 03 | "
                                  f"Carril: 2\nAplicación:  Recaudo\n{sintoma}Desde:       {hhmm(ticket.apertura)} | "
                                  f"Impacto: 1 carril\nPrioridad:   {prioridad} porque afecta el recaudo"))
    if es_p1:
        notas.append(_nota(t + timedelta(minutes=2), autor, f"[P1-INICIO] {hhmm(t)}\nDetección:  {hhmm(ticket.apertura)} "
                                                             f"por monitoreo\nAfectación: carriles 1 a 4\nAviso:      coordinador {hhmm(t)}"))
    diag = t + timedelta(minutes=rng.randint(15, 60))
    sigue = "Sigue:     revisar logs – yo" if rng.random() < 0.15 else f"Sigue:     revisar logs – yo – antes de {hhmm(diag + timedelta(hours=1))}"
    notas.append(_nota(diag, autor, f"[DIAG] {hhmm(diag)}\nHice:      1) reinicio del servicio 2) prueba de red\n"
                                    f"Encontré:  el servicio no responde\nEstado:    Hipótesis: bloqueo de base de datos\n{sigue}",
                       "TAREA", "" if rng.random() < 0.1 else "DIAG", "0" if rng.random() < 0.05 else str(rng.choice([15, 30, 45]))))
    estado_actual, desde = None, t
    for cambio in cambios:
        if cambio.estado is None:
            continue
        # Notas periódicas mientras el ticket sigue en el estado anterior
        paso = intervalo * (1.6 if rng.random() < 0.2 else 1)
        marcador = desde + paso
        while estado_actual not in ("Resueltas", "Cerrado", None) and marcador < cambio.fecha:
            if estado_actual == ESCALADO:
                notas.append(_nota(marcador, autor, f"[SEG-ESC] {marcador:%d/%m %H:%M}\nConsulté a: Desarrollo por Teams\n"
                                                    f"Respuesta:  sin respuesta\nSigue:      nuevo seguimiento – yo – {marcador + intervalo:%d/%m %H:%M}"))
            elif estado_actual == ESPERA:
                notas.append(_nota(marcador, autor, f"[RECORDATORIO n.º 1/2] {marcador:%d/%m %H:%M}\nContacté a operador por "
                                                    "llamada: sin respuesta"))
            elif es_p1:
                notas.append(_nota(marcador, autor, f"[P1-ACT] {hhmm(marcador)}\nEstado: sin cambios\nPróxima actualización: "
                                                    f"{hhmm(marcador + intervalo)}"))
            else:
                notas.append(_nota(marcador, autor, f"[AVANCE] {hhmm(marcador)}\nHice:      validación de la transmisión\n"
                                                    f"Estado:    sigue la falla\nSigue:     monitorear – yo – antes de {hhmm(marcador + intervalo)}"))
            marcador += paso
        f = cambio.fecha
        if cambio.estado == ESCALADO:
            solicita = "" if rng.random() < 0.15 else "\nSe solicita: corrección del servicio"
            notas.append(_nota(f, autor, f"[ESC] {hhmm(f)}\nEscalado a:  Desarrollo | Contacto: equipo | Medio: GLPI | "
                                         f"Ref.: #{ticket.id_glpi + 7}\nMotivo:      no se resuelve con el runbook\nPruebas:     "
                                         f"reinicio y revisión de logs\nEvidencias:  capturas adjuntas{solicita}"))
        elif estado_actual == ESCALADO:
            notas.append(_nota(f, autor, f"[RETORNO] {hhmm(f)}\nEl área Desarrollo respondió: se corrigió la versión\n"
                                         "Apliqué:    actualización\nVerificación: con el operador de la estación"))
        if cambio.estado == ESPERA:
            notas.append(_nota(f, autor, f"[ESPERA] {hhmm(f)}\nSe requiere de: operador\nQué:            confirmar horario\n"
                                         f"Recordatorio:   {f + timedelta(hours=24):%d/%m %H:%M}"))
        if cambio.estado == RESUELTO:
            if es_p1:
                notas.append(_nota(f - timedelta(minutes=5), autor, f"[P1-RESTABLECIDO] {hhmm(f)}\nServicio restablecido; "
                                                                    "verificado con el operador"))
            causa = "" if rng.random() < 0.15 else f"CAUSA: CAU-0{rng.randint(1, 7)} | detalle de la causa\n"
            verificacion = "" if rng.random() < 0.1 else f"\nVerificación: con el operador de la estación a las {hhmm(f)}"
            notas.append(_nota(f, autor, f"{causa}Se reinició el servicio y se validó la transmisión.{verificacion}", "SOLUCION"))
        estado_actual, desde = cambio.estado, f
    if rng.random() < 0.02:
        notas.append(_nota(t + timedelta(minutes=30), autor, "Se entregó la clave: 12345 al operador", privado=True))
    return sorted(notas, key=lambda n: n["fecha"])


def filas_seguimientos(tickets: list[TicketFicticio], corte: datetime, semilla: int = 0) -> list[dict]:
    filas = []
    for ticket in tickets:
        if ticket.apertura > corte:
            continue
        for nota in seguimientos_de(ticket, semilla):
            if nota["fecha"] <= corte:
                filas.append({"id_glpi": ticket.id_glpi, **nota})
    return filas


def texto_csv_seguimientos(filas: list[dict], separador_miles: str = " ") -> str:
    lineas = [";".join(_campo(e) for e in ENCABEZADOS_SEGUIMIENTOS) + ";"]
    for fila in filas:
        valores = (formatear_id(fila["id_glpi"], separador_miles), fila["fecha"], fila["autor"], _TIPO_TEXTO[fila["tipo"]],
                   "Sí" if fila["privado"] else "No", fila["contenido"], fila["categoria"], fila["duracion"])
        lineas.append(";".join(_campo(v) for v in valores) + ";")
    return "\n".join(lineas) + "\n"


def escribir_csv_seguimientos(filas: list[dict], ruta: Path, codificacion: str = "utf-8") -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(texto_csv_seguimientos(filas).encode(codificacion))
    return ruta


def _fecha(texto: str) -> datetime:
    return datetime.combine(date.fromisoformat(texto), time(0, 0))


def _fecha_fin(texto: str) -> datetime:
    return datetime.combine(date.fromisoformat(texto), time(23, 59))


def main(argumentos: list[str] | None = None) -> list[Path]:
    lector = argparse.ArgumentParser(
        description="Genera exportaciones CSV ficticias de GLPI (formato IMP-00)."
    )
    lector.add_argument("--tickets", type=int, default=300, help="cantidad de tickets")
    lector.add_argument("--desde", type=_fecha, default=None, help="AAAA-MM-DD (por defecto, 60 días antes de --hasta)")
    lector.add_argument("--hasta", type=_fecha_fin, default=None, help="AAAA-MM-DD (por defecto, hoy)")
    lector.add_argument("--cortes", type=int, default=1, help="exportaciones diarias a generar")
    lector.add_argument("--errores", type=int, default=0, help="filas con error en la última exportación")
    lector.add_argument("--semilla", type=int, default=42)
    lector.add_argument("--codificacion", default="utf-8", help="utf-8, utf-8-sig o latin-1")
    lector.add_argument("--separador-miles", default=" ", help="separador de miles del ID")
    lector.add_argument("--salida", type=Path, default=CARPETA_SALIDA)
    opciones = lector.parse_args(argumentos)

    hasta = opciones.hasta or datetime.combine(date.today(), time(23, 59))
    desde = opciones.desde or hasta - timedelta(days=60)
    if desde >= hasta:
        lector.error("--desde debe ser anterior a --hasta")
    rutas = generar_exportaciones(
        opciones.salida,
        opciones.tickets,
        desde,
        hasta,
        cortes=max(1, opciones.cortes),
        errores=opciones.errores,
        semilla=opciones.semilla,
        codificacion=opciones.codificacion,
        separador_miles=opciones.separador_miles,
    )
    for ruta in rutas:
        print(ruta)
    return rutas


if __name__ == "__main__":
    main()
