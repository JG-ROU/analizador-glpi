"""Valores del dominio fijados por la especificación (03: IMP-00, IMP-01, IMP-04).

Los textos de GLPI son solo los valores iniciales del perfil de importación;
el usuario puede cambiar el mapeo en pantalla.
"""

from dataclasses import dataclass

# Estados normalizados (estado_codigo)
NUEVO = "NUEVO"
EN_CURSO_ASIGNADO = "EN_CURSO_ASIGNADO"
EN_CURSO_PLANIFICADO = "EN_CURSO_PLANIFICADO"
EN_ESPERA = "EN_ESPERA"
ESCALADO = "ESCALADO"
RESUELTO = "RESUELTO"
CERRADO = "CERRADO"

ESTADOS = (
    NUEVO,
    EN_CURSO_ASIGNADO,
    EN_CURSO_PLANIFICADO,
    EN_ESPERA,
    ESCALADO,
    RESUELTO,
    CERRADO,
)
ESTADOS_SOLUCIONADOS = (RESUELTO, CERRADO)

MAPEO_ESTADOS_GLPI = {
    "Nuevo": NUEVO,
    "En curso (asignada)": EN_CURSO_ASIGNADO,
    "En curso (planificada)": EN_CURSO_PLANIFICADO,
    "En espera": EN_ESPERA,
    "Escalado": ESCALADO,
    "Resueltas": RESUELTO,
    "Cerrado": CERRADO,
}


@dataclass(frozen=True)
class Prioridad:
    nivel: int
    nombre: str  # texto de GLPI
    clave: str  # sufijo de los parámetros por prioridad


PRIORIDADES = (
    Prioridad(6, "Mayor", "mayor"),
    Prioridad(5, "Muy urgente", "muy_urgente"),
    Prioridad(4, "Urgente", "urgente"),
    Prioridad(3, "Mediana", "mediana"),
    Prioridad(2, "Baja", "baja"),
    Prioridad(1, "Muy baja", "muy_baja"),
)
MAPEO_PRIORIDADES_GLPI = {p.nombre: p.nivel for p in PRIORIDADES}

# Turnos que se asignan a un técnico (glosario). "Día Intermedio" no es franja de apertura.
TURNOS_TECNICO = ("Mañana", "Día Intermedio", "Tarde", "Nocturno")

# Tipos de caso del estándar de documentación
GESTION = "GESTION"
ESCALAMIENTO = "ESCALAMIENTO"
SOLICITUD = "SOLICITUD"
CRITICO_P1 = "CRITICO_P1"
ESPERA_EXTERNA = "ESPERA_EXTERNA"
CAMBIO = "CAMBIO"
ACTIVIDAD = "ACTIVIDAD"

TIPOS_CASO = (
    GESTION,
    ESCALAMIENTO,
    SOLICITUD,
    CRITICO_P1,
    ESPERA_EXTERNA,
    CAMBIO,
    ACTIVIDAD,
)
NOMBRE_TIPO_CASO = {
    GESTION: "Gestión",
    ESCALAMIENTO: "Escalamiento",
    SOLICITUD: "Solicitud",
    CRITICO_P1: "Crítico P1",
    ESPERA_EXTERNA: "En espera externa",
    CAMBIO: "Cambio/despliegue",
    ACTIVIDAD: "Actividad programada",
}
