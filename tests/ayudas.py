"""Ayudas para las pruebas: importar escenarios con el circuito real de importación."""

from datetime import datetime, timedelta
from pathlib import Path

import generador_glpi as gen
from core.fuentes.fuente_csv import FuenteCSV
from core.importacion import carga
from core.importacion import mapeo as m
from core.importacion import validacion as v
from core.turnos import interpretar_franja

FRANJAS = (
    interpretar_franja("Mañana", "06:00-14:00"),
    interpretar_franja("Tarde", "14:00-22:00"),
    interpretar_franja("Nocturno", "22:00-06:00"),
)


def perfil_glpi(bd, sesion):
    propuesto = m.PerfilImportacion(
        nombre="Exportación GLPI", separador=";", codificacion="utf-8",
        formato_fecha="%d-%m-%Y %H:%M", mapeo=m.Mapeo(columnas=m.proponer_columnas(gen.ENCABEZADOS)),
    )
    return m.guardar_perfil(bd, sesion, propuesto, gen.ENCABEZADOS)


def importar_archivo(bd, sesion, ruta: Path, carpeta: Path):
    perfil = perfil_glpi(bd, sesion)
    fuente = FuenteCSV(ruta)
    return carga.importar(
        bd, sesion, archivo=ruta.name, hash_archivo=fuente.hash, perfil=perfil,
        validacion=v.validar(fuente.obtener_tickets(), perfil), franjas=FRANJAS,
        carpeta_respaldos=carpeta / "respaldos", retencion_respaldos=30,
    )


def importar_diario(bd, sesion, tickets, desde: datetime, hasta: datetime, carpeta: Path) -> None:
    """Importa una exportación por día, a las 23:00, de `desde` a `hasta`.

    Si un día no hubo cambios, la exportación es idéntica a la anterior y se omite,
    como haría el usuario al recibir el aviso de archivo ya importado.
    """
    corte = desde.replace(hour=23, minute=0)
    while corte <= hasta:
        filas = gen.filas_en(tickets, corte)
        if filas:
            ruta = gen.escribir_csv(filas, carpeta / "csv" / f"glpi_{corte:%Y%m%d}.csv")
            if carga.importacion_previa(bd, FuenteCSV(ruta).hash) is None:
                importar_archivo(bd, sesion, ruta, carpeta)
        corte += timedelta(days=1)


def importar_seguimientos(bd, sesion, tickets, corte: datetime, carpeta: Path, filas=None):
    """Genera e importa el CSV de seguimientos de los tickets hasta el corte."""
    from core.importacion import seguimientos as seg

    filas = filas if filas is not None else gen.filas_seguimientos(tickets, corte)
    ruta = gen.escribir_csv_seguimientos(filas, carpeta / "csv" / f"seguimientos_{corte:%Y%m%d_%H%M}.csv")
    fuente = FuenteCSV(ruta)
    perfil = seg.proponer_perfil(fuente.formato)
    return seg.importar(bd, sesion, archivo=ruta.name, hash_archivo=fuente.hash, perfil=perfil,
                        validacion=seg.validar(bd, fuente.obtener_tickets(), perfil),
                        carpeta_respaldos=carpeta / "respaldos", retencion_respaldos=30)


def ticket(id_glpi, apertura, tecnico, prioridad, *cambios, estado_inicial=gen.ASIGNADO):
    """Ticket ficticio: `cambios` son pares (fecha, estado)."""
    return gen.TicketFicticio(
        id_glpi, f"Ticket {id_glpi}", gen.ENTIDAD_BASE, "Autor 001", "Depto > Filial > Cliente > Estación",
        apertura,
        cambios=[gen.Cambio(apertura, estado=estado_inicial, tecnicos=(tecnico,), prioridad=prioridad)]
        + [gen.Cambio(fecha, estado=estado) for fecha, estado in cambios],
    )
