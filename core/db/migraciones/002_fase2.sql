-- Fase 2: clasificación manual (IMP-07), hallazgos, snapshot, SEGMOV y paquete mensual (spec 04).

CREATE TABLE estacion (
    id             INTEGER PRIMARY KEY,
    nombre         TEXT NOT NULL UNIQUE,
    cliente        TEXT,
    incluir_segmov INTEGER NOT NULL DEFAULT 1 CHECK (incluir_segmov IN (0, 1)),
    activo         INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en      TEXT NOT NULL
) STRICT;

CREATE TABLE categoria (
    codigo          TEXT PRIMARY KEY,
    familia         TEXT NOT NULL,
    nivel1          TEXT NOT NULL,
    nivel2          TEXT,
    nivel3          TEXT,
    tipo_permitido  TEXT,
    nombre_completo TEXT NOT NULL,
    descripcion     TEXT,
    activo          INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
) STRICT;

CREATE TABLE causa (
    codigo      TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    descripcion TEXT,
    activo      INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
) STRICT;

CREATE TABLE tipo_solucion (
    codigo TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    nota   TEXT,
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
) STRICT;

-- La importación nunca escribe en esta tabla: la clasificación es del coordinador
CREATE TABLE ticket_clasificacion (
    ticket_id            INTEGER PRIMARY KEY REFERENCES ticket (id_glpi) ON DELETE CASCADE,
    estacion_id          INTEGER REFERENCES estacion (id),
    categoria_codigo     TEXT REFERENCES categoria (codigo),
    causa_codigo         TEXT REFERENCES causa (codigo),
    tipo_solucion_codigo TEXT REFERENCES tipo_solucion (codigo),
    actualizado_en       TEXT NOT NULL,
    usuario_id           INTEGER REFERENCES usuario (id)
) STRICT;

CREATE INDEX ix_clasificacion_estacion ON ticket_clasificacion (estacion_id);
CREATE INDEX ix_clasificacion_categoria ON ticket_clasificacion (categoria_codigo);

CREATE TABLE hallazgo (
    id             INTEGER PRIMARY KEY,
    regla          TEXT NOT NULL,
    severidad      TEXT NOT NULL CHECK (severidad IN ('ALTA', 'MEDIA', 'BAJA')),
    entidad_tipo   TEXT NOT NULL,
    entidad_valor  TEXT NOT NULL,
    periodo        TEXT NOT NULL,
    descripcion    TEXT NOT NULL,
    datos_json     TEXT NOT NULL,
    detectado_en   TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    estado         TEXT NOT NULL DEFAULT 'NUEVO'
                       CHECK (estado IN ('NUEVO', 'REVISADO', 'DESCARTADO', 'CERRADO')),
    comentario     TEXT,
    revisado_por   INTEGER REFERENCES usuario (id)
) STRICT;

-- Un hallazgo por regla, entidad y período: al volver a detectarlo se actualizan sus datos
CREATE UNIQUE INDEX ux_hallazgo_clave ON hallazgo (regla, entidad_tipo, entidad_valor, periodo);
CREATE INDEX ix_hallazgo_estado ON hallazgo (estado, severidad);

CREATE TABLE snapshot (
    periodo         TEXT NOT NULL,
    granularidad    TEXT NOT NULL CHECK (granularidad IN ('MES', 'SEMANA')),
    kpi_codigo      TEXT NOT NULL,
    dimension_tipo  TEXT NOT NULL,
    dimension_valor TEXT NOT NULL,
    valor           REAL,
    generado_en     TEXT NOT NULL,
    PRIMARY KEY (periodo, granularidad, kpi_codigo, dimension_tipo, dimension_valor)
) STRICT;

CREATE INDEX ix_snapshot_kpi ON snapshot (kpi_codigo, periodo);

CREATE TABLE segmov (
    periodo         TEXT NOT NULL,
    estacion_id     INTEGER NOT NULL REFERENCES estacion (id),
    casos           INTEGER NOT NULL,
    horas_asignadas REAL NOT NULL,
    total_horas     REAL NOT NULL,
    generado_en     TEXT NOT NULL,
    usuario_id      INTEGER REFERENCES usuario (id),
    PRIMARY KEY (periodo, estacion_id)
) STRICT;

CREATE TABLE paquete_mensual (
    periodo       TEXT PRIMARY KEY,
    generado_en   TEXT NOT NULL,
    usuario_id    INTEGER REFERENCES usuario (id),
    archivos_json TEXT NOT NULL
) STRICT;
