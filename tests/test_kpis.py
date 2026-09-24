"""KPIs de la Fase 1, semáforos y criticidad (spec 05, CA-06).

El escenario de septiembre de 2026 está armado para calcularse a mano. Todas las
horas son 10:00, así que las duraciones son días exactos.

| Ticket | Apertura | Prioridad | Técnico | Historia |
|---|---|---|---|---|
| T0 | 25-ago | Urgente | Tecnico 01 | resuelto 30-ago |
| T1 | 28-ago | Urgente | Tecnico 01 | escalado 2-sep, vuelve 3-sep, escalado 4-sep, resuelto 5-sep, cerrado 6-sep |
| A1 | 1-sep | Urgente | Tecnico 02 | resuelto 3-sep |
| A2 | 2-sep | Urgente | Tecnico 02 | resuelto 4-sep, cerrado 8-sep |
| A3 | 3-sep | Mediana | Tecnico 03 | escalado 6-sep, resuelto 2-oct |
| A4 | 5-sep | Mediana | Tecnico 03 | escalado 7-sep, vuelve 8-sep, resuelto 10-sep |
| A5–A10 | 11 a 16-sep | Mediana | Tecnico 04 | abiertos, sin actualizaciones |

Cálculo manual de septiembre (lo que haría el coordinador en Excel):
- Recibidos (apertura en septiembre): A1–A10 = 10.
- Soluciones en septiembre: T1, A1, A2, A4 = 4.
- Escalamientos en septiembre: T1 ×2, A3, A4 = 4.
- KPI-04 = (4 + 4) / 10 = 80 % → verde (≥ 80).
- KPI-05 = 4 / (4 + 4) = 50 % → rojo (> 35).
"""

from datetime import date, datetime

import pytest

import generador_glpi as gen
from ayudas import importar_diario, ticket
from core.analisis import periodos, semaforo
from core.analisis.filtros import Filtros
from core.analisis.kpis import CalculadoraKPI, criticidad_global
from core.errores import ErrorPermiso, ErrorValidacion
from core import seguridad


def d(mes, dia):
    return datetime(2026, mes, dia, 10, 0)


SEPTIEMBRE = periodos.mes(2026, 9)
AHORA = datetime(2026, 10, 5, 12, 0)


def escenario():
    tickets = [
        ticket(1, d(8, 25), "Tecnico 01", "Urgente", (d(8, 30), gen.RESUELTO)),
        ticket(2, d(8, 28), "Tecnico 01", "Urgente",
               (d(9, 2), gen.ESCALADO), (d(9, 3), gen.ASIGNADO), (d(9, 4), gen.ESCALADO),
               (d(9, 5), gen.RESUELTO), (d(9, 6), gen.CERRADO)),
        ticket(11, d(9, 1), "Tecnico 02", "Urgente", (d(9, 3), gen.RESUELTO)),
        ticket(12, d(9, 2), "Tecnico 02", "Urgente", (d(9, 4), gen.RESUELTO), (d(9, 8), gen.CERRADO)),
        ticket(13, d(9, 3), "Tecnico 03", "Mediana", (d(9, 6), gen.ESCALADO), (d(10, 2), gen.RESUELTO)),
        ticket(14, d(9, 5), "Tecnico 03", "Mediana",
               (d(9, 7), gen.ESCALADO), (d(9, 8), gen.ASIGNADO), (d(9, 10), gen.RESUELTO)),
    ]
    tickets += [ticket(20 + n, d(9, 11 + n), "Tecnico 04", "Mediana") for n in range(6)]
    return tickets


@pytest.fixture
def datos(bd, coordinador, tmp_path):
    importar_diario(bd, coordinador, escenario(), d(8, 25), datetime(2026, 10, 3, 23, 0), tmp_path)
    with bd:
        bd.execute("UPDATE parametro SET valor = '72' WHERE clave = 'sla_horas_urgente'")
        bd.execute("UPDATE parametro SET valor = '96' WHERE clave = 'sla_horas_mediana'")
    return bd


@pytest.fixture
def calc(datos, coordinador):
    return CalculadoraKPI(datos, coordinador, ahora=AHORA)


def tecnico_id(bd, nombre):
    return bd.execute("SELECT id FROM tecnico WHERE nombre_glpi = ?", (nombre,)).fetchone()[0]


# --- CA-06 ---

def test_ca06_kpi04_total_gestionados(calc):
    kpi = calc.calcular("KPI-04", SEPTIEMBRE)
    assert (kpi.numerador, kpi.denominador, kpi.valor) == (8, 10, 80.0)
    assert kpi.detalle == [{"soluciones": 4, "escalamientos": 4, "recibidos": 10}]
    assert kpi.semaforo == semaforo.VERDE
    assert kpi.meta == 100


def test_ca06_kpi05_tasa_de_escalamiento(calc):
    kpi = calc.calcular("KPI-05", SEPTIEMBRE)
    assert (kpi.numerador, kpi.denominador, kpi.valor) == (4, 8, 50.0)
    assert kpi.semaforo == semaforo.ROJO


@pytest.mark.parametrize(
    "valor, color",
    [(0, "VERDE"), (20, "VERDE"), (20.01, "AMARILLO"), (35, "AMARILLO"), (35.01, "ROJO"), (100, "ROJO")],
)
def test_ca06_semaforo_kpi05_respeta_20_y_35(valor, color):
    assert semaforo.evaluar(valor, "MENOR_MEJOR", 20, 35) == color


# --- Resto de KPIs de la Fase 1 ---

def test_kpi01_recibidos_y_variacion(calc):
    kpi = calc.calcular("KPI-01", SEPTIEMBRE)
    assert kpi.valor == 10
    assert kpi.valor_anterior == 2  # T0 y T1 en agosto
    assert kpi.variacion_porcentual == 400.0
    assert kpi.semaforo == semaforo.INFORMATIVO


def test_kpi02_resueltos(calc):
    assert calc.calcular("KPI-02", SEPTIEMBRE).valor == 4


def test_kpi03_backlog_al_corte(calc):
    kpi = calc.calcular("KPI-03", SEPTIEMBRE)
    # Al 1-oct siguen abiertos A3 (se resolvió el 2-oct) y A5–A10
    assert kpi.valor == 7
    assert {"prioridad": "Mediana", "abiertos": 7} in kpi.detalle
    assert calc.calcular("KPI-03", periodos.mes(2026, 10)).valor == 6


def test_kpi06_tiempo_de_resolucion(calc):
    kpi = calc.calcular("KPI-06", SEPTIEMBRE)
    # A1 48 h, A2 48 h, T1 192 h (Urgente); A4 120 h (Mediana)
    assert kpi.valor == 84.0 and kpi.cantidad == 4
    assert kpi.muestra_pequena and kpi.aproximado
    urgente = next(x for x in kpi.detalle if x["prioridad"] == "Urgente")
    assert (urgente["tickets"], urgente["mediana"]) == (3, 48.0)
    assert "Tiempos sin descontar espera" in kpi.notas
    assert kpi.semaforo == semaforo.INFORMATIVO  # sin umbrales por prioridad definidos


def test_kpi06_semaforo_por_prioridad(datos, coordinador):
    with datos:
        datos.execute("UPDATE parametro SET valor = '60' WHERE clave = 'kpi06_verde_horas_urgente'")
        datos.execute("UPDATE parametro SET valor = '100' WHERE clave = 'kpi06_verde_horas_mediana'")
    kpi = CalculadoraKPI(datos, coordinador, ahora=AHORA).calcular("KPI-06", SEPTIEMBRE)
    colores = {x["prioridad"]: x["semaforo"] for x in kpi.detalle}
    assert colores == {"Urgente": "VERDE", "Mediana": "ROJO"}
    assert kpi.semaforo == semaforo.ROJO


def test_kpi07_cumplimiento_sla(calc):
    kpi = calc.calcular("KPI-07", SEPTIEMBRE)
    # Objetivos: Urgente 72 h, Mediana 96 h → A1 y A2 a tiempo; T1 y A4 no
    assert (kpi.numerador, kpi.denominador, kpi.valor) == (2, 4, 50.0)
    assert kpi.semaforo == semaforo.ROJO


def test_kpi07_sin_objetivos_definidos(bd, coordinador, tmp_path):
    importar_diario(bd, coordinador, escenario(), d(8, 25), datetime(2026, 9, 12, 23, 0), tmp_path)
    kpi = CalculadoraKPI(bd, coordinador, ahora=AHORA).calcular("KPI-07", SEPTIEMBRE)
    assert kpi.valor is None and kpi.semaforo == semaforo.SIN_DATOS
    assert "Defina los objetivos de SLA" in kpi.notas[0]


def test_kpi08_resueltos_sin_cerrar(calc):
    kpi = calc.calcular("KPI-08", SEPTIEMBRE)
    # De los 4 resueltos en septiembre, A1 y A4 siguen sin cerrar al 1-oct
    assert (kpi.numerador, kpi.denominador, kpi.valor) == (2, 4, 50.0)
    assert kpi.semaforo == semaforo.ROJO


def test_kpi16_sin_actualizar(calc):
    kpi = calc.calcular("KPI-16", SEPTIEMBRE)
    # Abiertos al 1-oct: 7. A3 se actualizó el 2-oct (después del corte);
    # A5–A10 llevan más de 24 h sin actualización
    assert (kpi.numerador, kpi.denominador) == (6, 7)
    assert kpi.valor == 85.71


def test_kpi17_tiempo_en_escalado(calc):
    kpi = calc.calcular("KPI-17", SEPTIEMBRE)
    # Salidas de septiembre: T1 3-sep y 5-sep, A4 8-sep; 24 h cada una
    assert (kpi.cantidad, kpi.valor) == (3, 24.0)
    assert calc.calcular("KPI-17", periodos.mes(2026, 10)).valor == 624.0  # A3: 6-sep → 2-oct


# --- Filtros, permisos y criticidad ---

def test_filtro_por_tecnico(calc, datos):
    filtros = Filtros(tecnico_id=tecnico_id(datos, "Tecnico 03"))
    assert calc.calcular("KPI-01", SEPTIEMBRE, filtros).valor == 2
    kpi = calc.calcular("KPI-05", SEPTIEMBRE, filtros)
    assert (kpi.numerador, kpi.denominador) == (2, 3)


def test_filtro_por_prioridad_y_turno(calc):
    assert calc.calcular("KPI-01", SEPTIEMBRE, Filtros(prioridades=(4,))).valor == 2
    assert calc.calcular("KPI-01", SEPTIEMBRE, Filtros(turno="Mañana")).valor == 10
    assert calc.calcular("KPI-01", SEPTIEMBRE, Filtros(turno="Tarde")).valor == 0


def test_consulta_no_calcula_kpis_de_otro_tecnico(datos, coordinador):
    propio = tecnico_id(datos, "Tecnico 02")
    usuario = seguridad.crear_usuario(
        datos, coordinador, nombre="T2", perfil=seguridad.CONSULTA, pin="2222", tecnico_id=propio
    )
    sesion = seguridad.iniciar_sesion(datos, usuario, "2222")
    calc = CalculadoraKPI(datos, sesion, ahora=AHORA)
    assert calc.calcular("KPI-01", SEPTIEMBRE).valor == 10  # indicadores del equipo
    assert calc.calcular("KPI-01", SEPTIEMBRE, Filtros(tecnico_id=propio)).valor == 2
    with pytest.raises(ErrorPermiso):
        calc.calcular("KPI-01", SEPTIEMBRE, Filtros(tecnico_id=tecnico_id(datos, "Tecnico 03")))


def test_kpis_visibles_y_criticidad_global(calc, datos):
    with datos:
        datos.execute("UPDATE kpi_definicion SET visible_dashboard = 0 WHERE codigo = 'KPI-17'")
    calc = CalculadoraKPI(datos, calc.sesion, ahora=AHORA)
    resultados = calc.calcular_visibles(SEPTIEMBRE)
    assert [r.codigo for r in resultados] == [
        "KPI-01", "KPI-02", "KPI-03", "KPI-04", "KPI-05", "KPI-06", "KPI-07", "KPI-08",
        "KPI-09", "KPI-10", "KPI-11", "KPI-12", "KPI-13", "KPI-14", "KPI-15", "KPI-16",
    ]
    # Críticos: KPI-04 verde, KPI-05 rojo, KPI-07 rojo, KPI-08 rojo
    assert criticidad_global(resultados) == semaforo.ROJO


def test_umbral_editado_cambia_el_semaforo(datos, coordinador):
    with datos:
        datos.execute("UPDATE kpi_definicion SET umbral_verde = 55, umbral_amarillo = 60 WHERE codigo = 'KPI-05'")
    kpi = CalculadoraKPI(datos, coordinador, ahora=AHORA).calcular("KPI-05", SEPTIEMBRE)
    assert kpi.semaforo == semaforo.VERDE


def test_kpi_inexistente(calc):
    with pytest.raises(ErrorValidacion, match="no existe"):
        calc.calcular("KPI-99", SEPTIEMBRE)


def test_periodo_sin_datos(calc):
    kpi = calc.calcular("KPI-05", periodos.rango(date(2025, 1, 1), date(2025, 1, 31)))
    assert kpi.valor is None and kpi.semaforo == semaforo.SIN_DATOS


# --- Rendimiento (CA-07) ---

def test_kpis_del_dashboard_no_crecen_cuadraticamente(bd, coordinador, tmp_path):
    """Con 5.000 tickets el cálculo debe tomar décimas de segundo. Una consulta que
    recorra todos los eventos por cada ticket tardaría varios segundos."""
    import time

    from ayudas import importar_archivo

    tickets = gen.generar_tickets(5000, datetime(2024, 1, 1), datetime(2026, 9, 20), semilla=3)
    ruta = gen.escribir_csv(gen.filas_en(tickets, datetime(2026, 9, 21)), tmp_path / "volumen.csv")
    importar_archivo(bd, coordinador, ruta, tmp_path)
    calc = CalculadoraKPI(bd, coordinador, ahora=datetime(2026, 9, 21, 12))
    inicio = time.perf_counter()
    calc.calcular_visibles(SEPTIEMBRE)
    assert time.perf_counter() - inicio < 1.0


# --- Semáforo (función pura) ---

@pytest.mark.parametrize(
    "valor, direccion, verde, amarillo, color",
    [
        (80, "MAYOR_MEJOR", 80, 80, "VERDE"),
        (79.99, "MAYOR_MEJOR", 80, 80, "ROJO"),  # KPI-04: sin franja amarilla
        (85, "MAYOR_MEJOR", 90, 80, "AMARILLO"),
        (5, "MENOR_MEJOR", 5, None, "VERDE"),
        (5.01, "MENOR_MEJOR", 5, None, "ROJO"),  # KPI-08: sin umbral amarillo
        (10, "MENOR_MEJOR", None, None, "INFORMATIVO"),
        (10, "INFORMATIVO", 5, 8, "INFORMATIVO"),
        (None, "MAYOR_MEJOR", 90, 80, "SIN_DATOS"),
    ],
)
def test_evaluar_semaforo(valor, direccion, verde, amarillo, color):
    assert semaforo.evaluar(valor, direccion, verde, amarillo) == color


def test_peor_y_etiquetas():
    assert semaforo.peor(["VERDE", "INFORMATIVO", "AMARILLO"]) == "AMARILLO"
    assert semaforo.peor(["INFORMATIVO", "SIN_DATOS"]) == "SIN_DATOS"
    assert semaforo.etiqueta("ROJO") == "✖ Rojo" and semaforo.etiqueta("VERDE") == "✔ Verde"
