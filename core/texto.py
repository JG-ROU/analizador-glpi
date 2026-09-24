"""Normalización de textos para comparar nombres y títulos."""

import re
import unicodedata


def sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def normalizar_nombre(texto: str) -> str:
    """Para comparar nombres (estaciones): minúsculas, sin tildes y con espacios simples."""
    return " ".join(sin_tildes(texto).lower().split())


def normalizar_titulo(texto: str) -> str:
    """Para agrupar casos repetidos (HAL-01): sin mayúsculas, tildes, números ni signos.

    «Falla en carril 3 – Estación Norte» y «falla en CARRIL 5 estacion norte» dan
    el mismo resultado: «falla en carril estacion norte».
    """
    solo_letras = re.sub(r"[^a-z ]", " ", sin_tildes(texto).lower())
    return " ".join(solo_letras.split())


def ultimo_nivel(ruta: str | None) -> str | None:
    """Último nivel de una ruta jerárquica «A > B > C»; tolera espacios irregulares."""
    if not ruta:
        return None
    partes = [p.strip() for p in ruta.split(">") if p.strip()]
    return partes[-1] if partes else None
