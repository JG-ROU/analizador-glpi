"""Filtros de los indicadores (RN-01), traducidos a SQL parametrizado.

Nunca se arma SQL con valores del usuario: los valores van siempre como parámetros.
"""

from dataclasses import dataclass

from core import seguridad
from core.seguridad import Sesion


@dataclass(frozen=True)
class Filtros:
    tecnico_id: int | None = None
    turno: str | None = None
    prioridades: tuple[int, ...] = ()
    estados: tuple[str, ...] = ()
    tipos_caso: tuple[str, ...] = ()

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
                marcas = ", ".join("?" * len(valores))
                condiciones.append(f"{alias}.{columna} IN ({marcas})")
                parametros.extend(valores)
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
    permitido = seguridad.tecnico_permitido(sesion, filtros.tecnico_id)
    return Filtros(
        tecnico_id=permitido,
        turno=filtros.turno,
        prioridades=filtros.prioridades,
        estados=filtros.estados,
        tipos_caso=filtros.tipos_caso,
    )
