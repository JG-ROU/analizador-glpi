"""Condiciones de los KPIs creados por el usuario (KPI-00).

Un filtro es una lista de condiciones combinadas con Y, guardada como JSON:
    [{"campo": "familia", "valores": ["REC"]}, {"campo": "tiene_causa", "valor": false}]
Cada campo tiene un fragmento SQL fijo escrito en este módulo; los valores del
usuario van siempre como parámetros. Nunca se evalúa código escrito por el usuario.
La consulta usa los alias `t` (ticket) y `c` (ticket_clasificacion, LEFT JOIN).
"""

import json
from dataclasses import dataclass

from core.errores import ErrorValidacion

LISTA = "LISTA"
BOOLEANO = "BOOLEANO"
RANGO = "RANGO"
PREFIJO = "PREFIJO"


@dataclass(frozen=True)
class CampoFiltro:
    clave: str
    etiqueta: str
    tipo: str
    sql: str  # para LISTA: «expr IN ({})»; BOOLEANO: condición verdadera; RANGO: expresión; PREFIJO: expresión


CAMPOS_FILTRO = (
    CampoFiltro("estado", "Estado", LISTA, "t.estado_codigo IN ({})"),
    CampoFiltro("prioridad", "Prioridad (nivel)", LISTA, "t.prioridad_nivel IN ({})"),
    CampoFiltro("es_p1", "Es P1", BOOLEANO, "t.es_p1 = 1"),
    CampoFiltro("tecnico", "Técnico", LISTA, "t.tecnico_principal_id IN ({})"),
    CampoFiltro("turno", "Turno de apertura", LISTA, "t.turno_apertura IN ({})"),
    CampoFiltro("tipo_caso", "Tipo de caso", LISTA, "t.tipo_caso IN ({})"),
    CampoFiltro("escalado_actual", "Escalado actualmente", BOOLEANO, "t.escalado = 1"),
    CampoFiltro("tuvo_escalamiento", "Tuvo algún escalamiento", BOOLEANO,
                "EXISTS (SELECT 1 FROM ticket_evento e WHERE e.ticket_id = t.id_glpi AND e.tipo = 'ESCALAMIENTO')"),
    CampoFiltro("resuelto", "Resuelto o cerrado", BOOLEANO, "t.fecha_solucion IS NOT NULL"),
    CampoFiltro("reabierto", "Reabierto alguna vez", BOOLEANO,
                "EXISTS (SELECT 1 FROM ticket_evento e WHERE e.ticket_id = t.id_glpi AND e.tipo = 'REAPERTURA')"),
    CampoFiltro("horas_resolucion", "Horas de resolución", RANGO, "t.horas_resolucion"),
    CampoFiltro("estacion", "Estación", LISTA, "c.estacion_id IN ({})"),
    CampoFiltro("cliente", "Cliente", LISTA, "c.estacion_id IN (SELECT id FROM estacion WHERE cliente IN ({}))"),
    CampoFiltro("familia", "Familia de categoría", LISTA, "substr(c.categoria_codigo, 1, 3) IN ({})"),
    CampoFiltro("categoria", "Código de categoría", LISTA, "c.categoria_codigo IN ({})"),
    CampoFiltro("categoria_prefijo", "Código de categoría que empieza por", PREFIJO, "c.categoria_codigo"),
    CampoFiltro("causa", "Causa", LISTA, "c.causa_codigo IN ({})"),
    CampoFiltro("tiene_causa", "Tiene causa", BOOLEANO, "c.causa_codigo IS NOT NULL"),
    CampoFiltro("clasificado", "Clasificado por completo", BOOLEANO,
                "(c.estacion_id IS NOT NULL AND c.categoria_codigo IS NOT NULL AND c.causa_codigo IS NOT NULL "
                "AND c.tipo_solucion_codigo IS NOT NULL)"),
)
CAMPOS_POR_CLAVE = {c.clave: c for c in CAMPOS_FILTRO}


def opciones(conexion, turnos: list[str]) -> dict[str, list[tuple[object, str]]]:
    """Valores posibles de cada condición de tipo LISTA, para el editor (valor, texto)."""
    from core.analisis.kpis import NOMBRE_PRIORIDAD
    from core.analisis.series import NOMBRE_ESTADO
    from core.dominio import NOMBRE_TIPO_CASO

    def consulta(sql):
        return [(f[0], f[1]) for f in conexion.execute(sql)]

    return {
        "estado": list(NOMBRE_ESTADO.items()),
        "prioridad": [(n, NOMBRE_PRIORIDAD[n]) for n in sorted(NOMBRE_PRIORIDAD, reverse=True)],
        "tecnico": consulta("SELECT id, nombre_mostrar FROM tecnico ORDER BY nombre_mostrar"),
        "turno": [(t, t) for t in turnos],
        "tipo_caso": list(NOMBRE_TIPO_CASO.items()),
        "estacion": consulta("SELECT id, nombre FROM estacion ORDER BY nombre"),
        "cliente": consulta("SELECT DISTINCT cliente, cliente FROM estacion WHERE cliente IS NOT NULL ORDER BY 1"),
        "familia": consulta("SELECT DISTINCT familia, nivel1 FROM categoria ORDER BY familia"),
        "categoria": consulta("SELECT codigo, COALESCE(nivel3, nivel2) FROM categoria ORDER BY codigo"),
        "causa": consulta("SELECT codigo, codigo || ' ' || nombre FROM causa ORDER BY codigo"),
    }


def leer(texto: str | None) -> list[dict]:
    """Lista de condiciones de un filtro guardado (vacío = sin condiciones)."""
    if not texto:
        return []
    try:
        condiciones = json.loads(texto)
    except json.JSONDecodeError as error:
        raise ErrorValidacion("El filtro guardado del KPI está dañado.", detalle=repr(error)) from error
    validar(condiciones)
    return condiciones


def a_texto(condiciones: list[dict]) -> str | None:
    validar(condiciones)
    return json.dumps(condiciones, ensure_ascii=False) if condiciones else None


def validar(condiciones) -> None:
    if not isinstance(condiciones, list):
        raise ErrorValidacion("Un filtro debe ser una lista de condiciones.")
    for condicion in condiciones:
        campo = CAMPOS_POR_CLAVE.get(condicion.get("campo")) if isinstance(condicion, dict) else None
        if campo is None:
            raise ErrorValidacion(f"Condición desconocida: {condicion!r}.")
        if campo.tipo == LISTA:
            valores = condicion.get("valores")
            if not isinstance(valores, list) or not valores:
                raise ErrorValidacion(f"Elija al menos un valor para «{campo.etiqueta}».")
        elif campo.tipo == BOOLEANO:
            if not isinstance(condicion.get("valor"), bool):
                raise ErrorValidacion(f"Indique Sí o No para «{campo.etiqueta}».")
        elif campo.tipo == RANGO:
            minimo, maximo = condicion.get("min"), condicion.get("max")
            if minimo is None and maximo is None:
                raise ErrorValidacion(f"Indique un mínimo o un máximo para «{campo.etiqueta}».")
            for limite in (minimo, maximo):
                if limite is not None and not isinstance(limite, (int, float)):
                    raise ErrorValidacion(f"Los límites de «{campo.etiqueta}» deben ser números.")
        elif campo.tipo == PREFIJO:
            if not isinstance(condicion.get("valor"), str) or not condicion["valor"].strip():
                raise ErrorValidacion(f"Escriba el prefijo de «{campo.etiqueta}».")


def a_sql(condiciones: list[dict]) -> tuple[str, list]:
    """«AND …» con las condiciones y sus parámetros."""
    validar(condiciones)
    partes, parametros = [], []
    for condicion in condiciones:
        campo = CAMPOS_POR_CLAVE[condicion["campo"]]
        if campo.tipo == LISTA:
            valores = condicion["valores"]
            partes.append(campo.sql.format(", ".join("?" * len(valores))))
            parametros.extend(valores)
        elif campo.tipo == BOOLEANO:
            partes.append(campo.sql if condicion["valor"] else f"NOT ({campo.sql})")
        elif campo.tipo == RANGO:
            if condicion.get("min") is not None:
                partes.append(f"{campo.sql} >= ?")
                parametros.append(condicion["min"])
            if condicion.get("max") is not None:
                partes.append(f"{campo.sql} <= ?")
                parametros.append(condicion["max"])
        else:
            partes.append(f"{campo.sql} LIKE ? ESCAPE '\\'")
            prefijo = condicion["valor"].strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parametros.append(prefijo + "%")
    return "".join(f" AND {p}" for p in partes), parametros


def describir(condiciones: list[dict], nombres: dict[str, dict] | None = None) -> str:
    """Texto legible, por ejemplo «Familia de categoría: REC y Tiene causa: No»."""
    if not condiciones:
        return "Todos los tickets"
    nombres = nombres or {}
    textos = []
    for condicion in condiciones:
        campo = CAMPOS_POR_CLAVE[condicion["campo"]]
        if campo.tipo == LISTA:
            traduccion = nombres.get(campo.clave, {})
            valor = ", ".join(str(traduccion.get(v, v)) for v in condicion["valores"])
        elif campo.tipo == BOOLEANO:
            valor = "Sí" if condicion["valor"] else "No"
        elif campo.tipo == RANGO:
            valor = f"{condicion.get('min', '')} a {condicion.get('max', '')}".strip()
        else:
            valor = f"{condicion['valor']}…"
        textos.append(f"{campo.etiqueta}: {valor}")
    return " y ".join(textos)
