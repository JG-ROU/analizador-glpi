-- Fase 1: importación de tickets, KPIs, usuarios, parámetros e historial (spec 04).
-- Fechas en texto ISO 8601 (AAAA-MM-DD HH:MM:SS), hora local de Bogotá.

CREATE TABLE migracion (
    version     INTEGER PRIMARY KEY,
    nombre      TEXT NOT NULL,
    aplicada_en TEXT NOT NULL
) STRICT;

CREATE TABLE tecnico (
    id                 INTEGER PRIMARY KEY,
    nombre_glpi        TEXT NOT NULL UNIQUE,
    nombre_mostrar     TEXT NOT NULL,
    turno              TEXT,
    activo             INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    incluir_en_ranking INTEGER NOT NULL DEFAULT 1 CHECK (incluir_en_ranking IN (0, 1)),
    creado_en          TEXT NOT NULL
) STRICT;

CREATE TABLE usuario (
    id         INTEGER PRIMARY KEY,
    nombre     TEXT NOT NULL UNIQUE,
    perfil     TEXT NOT NULL CHECK (perfil IN ('COORDINADOR', 'CONSULTA')),
    tecnico_id INTEGER REFERENCES tecnico (id),
    pin_hash   TEXT NOT NULL,
    activo     INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en  TEXT NOT NULL
) STRICT;

CREATE TABLE perfil_importacion (
    id                     INTEGER PRIMARY KEY,
    nombre                 TEXT NOT NULL UNIQUE,
    separador              TEXT NOT NULL,
    codificacion           TEXT NOT NULL,
    formato_fecha          TEXT NOT NULL,
    separador_multivalor   TEXT NOT NULL,
    mapeo_json             TEXT NOT NULL,
    mapeo_estados_json     TEXT NOT NULL,
    mapeo_prioridades_json TEXT NOT NULL,
    creado_en              TEXT NOT NULL,
    actualizado_en         TEXT NOT NULL
) STRICT;

CREATE TABLE importacion (
    id                INTEGER PRIMARY KEY,
    tipo              TEXT NOT NULL CHECK (tipo IN ('TICKETS', 'SEGUIMIENTOS')),
    archivo           TEXT NOT NULL,
    hash              TEXT NOT NULL,
    perfil_id         INTEGER REFERENCES perfil_importacion (id),
    usuario_id        INTEGER REFERENCES usuario (id),
    fecha             TEXT NOT NULL,
    filas_leidas      INTEGER NOT NULL DEFAULT 0,
    filas_validas     INTEGER NOT NULL DEFAULT 0,
    filas_advertencia INTEGER NOT NULL DEFAULT 0,
    filas_error       INTEGER NOT NULL DEFAULT 0,
    fecha_min         TEXT,
    fecha_max         TEXT
) STRICT;

CREATE UNIQUE INDEX ux_importacion_hash ON importacion (tipo, hash);

CREATE TABLE ticket (
    id_glpi                INTEGER PRIMARY KEY,
    titulo                 TEXT NOT NULL,
    entidad                TEXT,
    estado                 TEXT NOT NULL,
    estado_codigo          TEXT NOT NULL CHECK (estado_codigo IN (
                               'NUEVO', 'EN_CURSO_ASIGNADO', 'EN_CURSO_PLANIFICADO',
                               'EN_ESPERA', 'ESCALADO', 'RESUELTO', 'CERRADO')),
    prioridad              TEXT NOT NULL,
    prioridad_nivel        INTEGER NOT NULL CHECK (prioridad_nivel BETWEEN 1 AND 6),
    es_p1                  INTEGER NOT NULL DEFAULT 0 CHECK (es_p1 IN (0, 1)),
    fecha_apertura         TEXT NOT NULL,
    ultima_actualizacion   TEXT NOT NULL,
    fecha_solucion         TEXT,
    fecha_cierre           TEXT,
    autor                  TEXT,
    ubicacion              TEXT,
    tecnico_principal_id   INTEGER REFERENCES tecnico (id),
    escalado               INTEGER NOT NULL DEFAULT 0 CHECK (escalado IN (0, 1)),
    tipo_caso              TEXT NOT NULL CHECK (tipo_caso IN (
                               'GESTION', 'ESCALAMIENTO', 'SOLICITUD', 'CRITICO_P1',
                               'ESPERA_EXTERNA', 'CAMBIO', 'ACTIVIDAD')),
    tipo_caso_origen       TEXT NOT NULL DEFAULT 'INFERIDO'
                               CHECK (tipo_caso_origen IN ('INFERIDO', 'MANUAL')),
    turno_apertura         TEXT NOT NULL,
    horas_resolucion       REAL,
    horas_hasta_cierre     REAL,
    hash_fila              TEXT NOT NULL,
    primera_importacion_id INTEGER NOT NULL REFERENCES importacion (id),
    ultima_importacion_id  INTEGER NOT NULL REFERENCES importacion (id)
) STRICT;

CREATE INDEX ix_ticket_fecha_apertura ON ticket (fecha_apertura);
CREATE INDEX ix_ticket_tecnico ON ticket (tecnico_principal_id);
CREATE INDEX ix_ticket_estado ON ticket (estado_codigo);
CREATE INDEX ix_ticket_prioridad ON ticket (prioridad_nivel);

CREATE TABLE ticket_tecnico (
    ticket_id  INTEGER NOT NULL REFERENCES ticket (id_glpi) ON DELETE CASCADE,
    tecnico_id INTEGER NOT NULL REFERENCES tecnico (id),
    orden      INTEGER NOT NULL,
    PRIMARY KEY (ticket_id, tecnico_id)
) STRICT;

CREATE TABLE ticket_cambio (
    id             INTEGER PRIMARY KEY,
    ticket_id      INTEGER NOT NULL REFERENCES ticket (id_glpi) ON DELETE CASCADE,
    importacion_id INTEGER NOT NULL REFERENCES importacion (id),
    campo          TEXT NOT NULL CHECK (campo IN ('estado', 'tecnico', 'prioridad')),
    valor_anterior TEXT,
    valor_nuevo    TEXT,
    detectado_en   TEXT NOT NULL
) STRICT;

CREATE INDEX ix_ticket_cambio_ticket ON ticket_cambio (ticket_id);

CREATE TABLE ticket_evento (
    id             INTEGER PRIMARY KEY,
    ticket_id      INTEGER NOT NULL REFERENCES ticket (id_glpi) ON DELETE CASCADE,
    importacion_id INTEGER NOT NULL REFERENCES importacion (id),
    tipo           TEXT NOT NULL CHECK (tipo IN (
                       'ESCALAMIENTO', 'SALIDA_ESCALADO', 'SOLUCION', 'CIERRE', 'REAPERTURA')),
    fecha_evento   TEXT NOT NULL,
    origen         TEXT NOT NULL CHECK (origen IN ('TRANSICION', 'PRIMERA_VEZ')),
    tecnico_id     INTEGER REFERENCES tecnico (id)
) STRICT;

CREATE INDEX ix_ticket_evento_tipo_fecha ON ticket_evento (tipo, fecha_evento);
CREATE INDEX ix_ticket_evento_ticket ON ticket_evento (ticket_id);

CREATE TABLE kpi_definicion (
    id                      INTEGER PRIMARY KEY,
    codigo                  TEXT NOT NULL UNIQUE,
    nombre                  TEXT NOT NULL,
    descripcion             TEXT NOT NULL,
    tipo_calculo            TEXT NOT NULL CHECK (tipo_calculo IN (
                                'CONTEO', 'PORCENTAJE', 'MEDIANA_TIEMPO', 'PROMEDIO_TIEMPO',
                                'P90_TIEMPO', 'CONTEO_EVENTOS')),
    calculo_especial        TEXT,
    filtro_numerador_json   TEXT,
    filtro_denominador_json TEXT,
    campo_tiempo            TEXT,
    unidad                  TEXT NOT NULL,
    direccion               TEXT NOT NULL CHECK (direccion IN (
                                'MAYOR_MEJOR', 'MENOR_MEJOR', 'INFORMATIVO')),
    umbral_verde            REAL,
    umbral_amarillo         REAL,
    meta                    REAL,
    aproximado              INTEGER NOT NULL DEFAULT 0 CHECK (aproximado IN (0, 1)),
    critico                 INTEGER NOT NULL DEFAULT 0 CHECK (critico IN (0, 1)),
    predefinido             INTEGER NOT NULL DEFAULT 0 CHECK (predefinido IN (0, 1)),
    visible_dashboard       INTEGER NOT NULL DEFAULT 1 CHECK (visible_dashboard IN (0, 1)),
    orden                   INTEGER NOT NULL DEFAULT 0,
    activo                  INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
) STRICT;

CREATE TABLE festivo (
    fecha       TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL
) STRICT;

CREATE TABLE parametro (
    clave       TEXT PRIMARY KEY,
    valor       TEXT,
    tipo        TEXT NOT NULL CHECK (tipo IN ('ENTERO', 'DECIMAL', 'TEXTO', 'BOOLEANO')),
    grupo       TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    minimo      REAL,
    maximo      REAL
) STRICT;

CREATE TABLE historial (
    id             INTEGER PRIMARY KEY,
    entidad        TEXT NOT NULL,
    entidad_id     TEXT,
    accion         TEXT NOT NULL,
    campo          TEXT,
    valor_anterior TEXT,
    valor_nuevo    TEXT,
    nota           TEXT,
    usuario_id     INTEGER REFERENCES usuario (id),
    fecha_hora     TEXT NOT NULL
) STRICT;

CREATE INDEX ix_historial_entidad ON historial (entidad, entidad_id);

-- RNF-09: el historial es de solo inserción
CREATE TRIGGER tr_historial_sin_update BEFORE UPDATE ON historial
BEGIN
    SELECT RAISE(ABORT, 'El historial es de solo inserción');
END;

CREATE TRIGGER tr_historial_sin_delete BEFORE DELETE ON historial
BEGIN
    SELECT RAISE(ABORT, 'El historial es de solo inserción');
END;
