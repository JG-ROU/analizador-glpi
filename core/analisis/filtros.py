"""Filtros de los indicadores (RN-01), traducidos a SQL parametrizado.

Nunca se arma SQL con valores del usuario: los valores van siempre como parámetros.
Los filtros de clasificación (estación, cliente, familia, categoría, causa) usan
la clasificación manual (IMP-07).
"""

from dataclasses import dataclass, replace

from core import seguridad
from core.seguridad import Sesion


def _marcas(valores) -> str:
    return ", ".join("?" * len(valores))


@dataclass(frozen=True)
class Filtros:
    tecnico_id: int | None = None
    turno: str | None = None
    prioridades: tuple[int, ...] = ()
    estados: tuple[str, ...] = ()
    tipos_caso: tuple[str, ...] = ()
    estaciones: tuple[int, ...] = ()
    clientes: tuple[str, ...] = ()
    familias: tuple[str, ...] = ()
    categorias: tuple[str, ...] = ()
    causas: tuple[str, ...] = ()

    def sql(self, alias: str = "t") -> tuple[str, list]:
        """Condiciones «AND …» sobre la tabla ticket (con el alias dado) y sus parámetros."""
        condiciones, parametros = [], []
        if self.tecnico_id is not None:
            condiciones.append(f"{alias}.tecnico_principal_id = ?")
            parametros.append(self.tecnico_id)
        if self.turno:
            condiciones.append(f"{alias}.turno_apertura = ?")
            parametros.append(self.turno)
        for columna, valores in (
            ("prioridad_nivel", self.prioridades),
            ("estado_codigo", self.estados),
            ("tipo_caso", self.tipos_caso),
        ):
            if valores:
                condiciones.append(f"{alias}.{columna} IN ({_marcas(valores)})")
                parametros.extend(valores)
        clasificacion, valores_clasificacion = [], []
        for plantilla, valores in (
            ("c.estacion_id IN ({})", self.estaciones),
            ("c.estacion_id IN (SELECT id FROM estacion WHERE cliente IN ({}))", self.clientes),
            ("substr(c.categoria_codigo, 1, 3) IN ({})", self.familias),
            ("c.categoria_codigo IN ({})", self.categorias),
            ("c.causa_codigo IN ({})", self.causas),
        ):
            if valores:
                clasificacion.append(plantilla.format(_marcas(valores)))
                valores_clasificacion.extend(valores)
        if clasificacion:
            condiciones.append(
                f"{alias}.id_glpi IN (SELECT c.ticket_id FROM ticket_clasificacion c "
                f"WHERE {' AND '.join(clasificacion)})"
            )
            parametros.extend(valores_clasificacion)
        texto = "".join(f" AND {c}" for c in condiciones)
        return texto, parametros


def filtros_permitidos(sesion: Sesion, filtros: Filtros) -> Filtros:
    """Aplica los permisos de la sesión (RNF-07).

    Los indicadores del equipo (sin técnico) los ve cualquier usuario. Si se pide
    un técnico, solo el coordinador puede elegir cualquiera; un usuario de
    consulta solo el propio.
    """
    if filtros.tecnico_id is None:
        return filtros
    return replace(filtros, tecnico_id=seguridad.tecnico_permitido(sesion, filtros.tecnico_id))
