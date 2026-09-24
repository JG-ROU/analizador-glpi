-- Fase 3: seguimientos, criterios de calidad y evaluaciones (spec 04 y 07).

CREATE TABLE seguimiento (
    id             INTEGER PRIMARY KEY,
    ticket_id      INTEGER NOT NULL REFERENCES ticket (id_glpi) ON DELETE CASCADE,
    fecha          TEXT NOT NULL,
    autor          TEXT,
    tipo           TEXT NOT NULL CHECK (tipo IN ('SEGUIMIENTO', 'TAREA', 'SOLUCION')),
    privado        INTEGER NOT NULL DEFAULT 0 CHECK (privado IN (0, 1)),
    contenido      TEXT NOT NULL,
    categoria_tarea TEXT,
    duracion_min   REAL,
    etiqueta       TEXT,
    huella         TEXT NOT NULL UNIQUE,
    importacion_id INTEGER NOT NULL REFERENCES importacion (id)
) STRICT;

CREATE INDEX ix_seguimiento_ticket_fecha ON seguimiento (ticket_id, fecha);

CREATE TABLE criterio_calidad (
    id            TEXT PRIMARY KEY,
    aplica_a      TEXT NOT NULL,
    descripcion   TEXT NOT NULL,
    como_verificar TEXT,
    critico       INTEGER NOT NULL CHECK (critico IN (0, 1)),
    automatizable TEXT NOT NULL CHECK (automatizable IN ('Auto', 'Semi', 'Manual')),
    regla         TEXT,
    activo        INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
) STRICT;

CREATE TABLE evaluacion (
    id                INTEGER PRIMARY KEY,
    ticket_id         INTEGER NOT NULL REFERENCES ticket (id_glpi) ON DELETE CASCADE,
    tipo_caso         TEXT NOT NULL,
    auditor_id        INTEGER REFERENCES usuario (id),
    fecha             TEXT NOT NULL,
    porcentaje        REAL,
    criticos_fallidos INTEGER NOT NULL,
    resultado         TEXT NOT NULL CHECK (resultado IN ('CONFORME', 'POR_MEJORAR', 'NO_CONFORME')),
    retroalimentacion TEXT,
    version           INTEGER NOT NULL,
    vigente           INTEGER NOT NULL DEFAULT 1 CHECK (vigente IN (0, 1)),
    UNIQUE (ticket_id, version)
) STRICT;

CREATE INDEX ix_evaluacion_vigente ON evaluacion (vigente, fecha);

CREATE TABLE evaluacion_detalle (
    evaluacion_id INTEGER NOT NULL REFERENCES evaluacion (id) ON DELETE CASCADE,
    criterio_id   TEXT NOT NULL REFERENCES criterio_calidad (id),
    resultado     TEXT NOT NULL CHECK (resultado IN ('C', 'N', 'NA')),
    origen        TEXT NOT NULL CHECK (origen IN ('MANUAL', 'AUTO', 'AUTO_CORREGIDO')),
    nota          TEXT,
    PRIMARY KEY (evaluacion_id, criterio_id)
) STRICT;

-- Muestra semanal sugerida para auditar (CAL-04); el coordinador puede agregar o quitar
CREATE TABLE muestra_auditoria (
    semana    TEXT NOT NULL,
    ticket_id INTEGER NOT NULL REFERENCES ticket (id_glpi) ON DELETE CASCADE,
    motivo    TEXT NOT NULL,
    PRIMARY KEY (semana, ticket_id)
) STRICT;
