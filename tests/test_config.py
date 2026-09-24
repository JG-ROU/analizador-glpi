from pathlib import Path

import pytest

from core import config
from core.errores import ErrorConfiguracion

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = (RAIZ / "config.ini.ejemplo").read_text(encoding="utf-8")


def escribir(tmp_path: Path, texto: str, codificacion: str = "utf-8") -> Path:
    archivo = tmp_path / "config.ini"
    archivo.write_text(texto, encoding=codificacion)
    return archivo


def test_plantilla_del_proyecto_es_valida(tmp_path):
    cfg = config.cargar(escribir(tmp_path, PLANTILLA), tmp_path)
    assert cfg.importacion.separador_por_defecto == ";"
    assert cfg.importacion.codificacion_por_defecto == "utf-8-sig"
    assert cfg.importacion.formato_fecha == "%d-%m-%Y %H:%M"
    assert cfg.importacion.tamano_bloque == 5000
    assert cfg.general.nivel_log == "INFO"
    assert cfg.general.retencion_respaldos == 30
    assert [f.turno for f in cfg.turnos] == ["Mañana", "Tarde", "Nocturno"]


def test_rutas_relativas_se_resuelven_desde_la_base(tmp_path):
    cfg = config.cargar(escribir(tmp_path, PLANTILLA), tmp_path)
    assert cfg.rutas.base_datos == tmp_path / "data" / "analizador.db"
    assert cfg.rutas.respaldos == tmp_path / "data" / "respaldos"
    assert cfg.rutas.logs == tmp_path / "logs"
    assert cfg.rutas.carpetas()[0] == tmp_path / "data"


def test_ruta_absoluta_se_respeta(tmp_path):
    absoluta = tmp_path / "otra" / "exportaciones"
    texto = PLANTILLA.replace("exportaciones = exportaciones", f"exportaciones = {absoluta}")
    cfg = config.cargar(escribir(tmp_path, texto), tmp_path / "base")
    assert cfg.rutas.exportaciones == absoluta


def test_archivo_guardado_en_codificacion_de_windows(tmp_path):
    cfg = config.cargar(escribir(tmp_path, PLANTILLA, "cp1252"), tmp_path)
    assert cfg.turnos[0].turno == "Mañana"


def test_asegurar_archivo_copia_la_plantilla_si_falta(tmp_path):
    base, recursos = tmp_path / "base", tmp_path / "recursos"
    base.mkdir()
    recursos.mkdir()
    (recursos / "config.ini.ejemplo").write_text(PLANTILLA, encoding="utf-8")
    archivo = config.asegurar_archivo(base, recursos)
    assert archivo == base / "config.ini"
    assert archivo.read_text(encoding="utf-8") == PLANTILLA


def test_asegurar_archivo_no_sobrescribe_el_existente(tmp_path):
    (tmp_path / "config.ini").write_text("propio", encoding="utf-8")
    (tmp_path / "config.ini.ejemplo").write_text(PLANTILLA, encoding="utf-8")
    config.asegurar_archivo(tmp_path, tmp_path)
    assert (tmp_path / "config.ini").read_text(encoding="utf-8") == "propio"


def test_sin_archivo_ni_plantilla(tmp_path):
    with pytest.raises(ErrorConfiguracion, match="plantilla"):
        config.asegurar_archivo(tmp_path, tmp_path)


@pytest.mark.parametrize(
    "buscar, reemplazo, mensaje",
    [
        ("[turnos]", "[turnos_x]", r"\[turnos\]"),
        ("tamano_bloque = 5000", "tamano_bloque = mucho", "tamano_bloque"),
        ("tamano_bloque = 5000", "tamano_bloque = 10", "mayor o igual a 100"),
        ("retencion_respaldos = 30", "retencion_respaldos = 0", "retencion_respaldos"),
        ("nivel_log = INFO", "nivel_log = TODO", "nivel_log"),
        ("separador_por_defecto = ;", "separador_por_defecto = ;;", "un solo carácter"),
        ("codificacion_por_defecto = utf-8-sig", "codificacion_por_defecto = xyz", "xyz"),
        ("logs = logs", "logs =", "«logs»"),
        ("Nocturno = 22:00-06:00", "Nocturno = 22:00-07:00", "se solapan"),
        ("[rutas]", "rutas", "formato"),
    ],
)
def test_valores_invalidos_dan_mensaje_en_espanol(tmp_path, buscar, reemplazo, mensaje):
    texto = PLANTILLA.replace(buscar, reemplazo)
    with pytest.raises(ErrorConfiguracion, match=mensaje):
        config.cargar(escribir(tmp_path, texto), tmp_path)
