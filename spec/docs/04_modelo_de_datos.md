# 04 – Modelo de datos (SQLite)

> **Ajuste del 2026-09-24.** Modelo adaptado a la exportación real de 10 columnas (ver `03`) y a las decisiones tomadas con el coordinador.

**Convenciones:**
- `PRAGMA foreign_keys=ON` y modo WAL.
- Fechas en texto ISO 8601, en hora local de Colombia (America/Bogota), sin zona.
- Acceso con `sqlite3` de la biblioteca estándar.
- **Migraciones versionadas** en `core/db/migraciones/NNN_*.sql`, controladas con `PRAGMA user_version` y la tabla `migracion`. Antes de migrar se saca un respaldo.
- **Creación por fase:** cada fase crea solo sus tablas, con su propia migración (columna "Fase").

| Tabla | Fase | Campos principales | Notas |
|---|---|---|---|
| migracion | 1 | version (PK), nombre, aplicada_en | Control de migraciones |
| importacion | 1 | id, tipo (TICKETS / SEGUIMIENTOS), archivo, hash, perfil_id, usuario_id, fecha, filas_leidas, filas_validas, filas_advertencia, filas_error, fecha_min, fecha_max | IMP-03 |
| perfil_importacion | 1 | id, nombre, separador, codificacion, formato_fecha, separador_multivalor, mapeo_json, mapeo_estados_json, mapeo_prioridades_json | IMP-01 |
| ticket | 1 | id_glpi (PK), titulo, entidad, estado, estado_codigo, prioridad, prioridad_nivel, es_p1, fecha_apertura, ultima_actualizacion, fecha_solucion, fecha_cierre, autor, ubicacion, tecnico_principal_id (FK tecnico), escalado, tipo_caso, tipo_caso_origen (INFERIDO / MANUAL), turno_apertura, horas_resolucion, horas_hasta_cierre, hash_fila, primera_importacion_id, ultima_importacion_id | Derivados según IMP-04. `fecha_solucion` y `fecha_cierre` son aproximadas (IMP-06) |
| ticket_tecnico | 1 | ticket_id, tecnico_id, orden | Varios técnicos por ticket |
| ticket_cambio | 1 | id, ticket_id, importacion_id, campo (estado / tecnico / prioridad), valor_anterior, valor_nuevo, detectado_en | IMP-03 |
| ticket_evento | 1 | id, ticket_id, importacion_id, tipo (ESCALAMIENTO / SALIDA_ESCALADO / SOLUCION / CIERRE / REAPERTURA), fecha_evento, origen (TRANSICION / PRIMERA_VEZ), tecnico_id | IMP-06. Base de KPI-02, 04, 05, 12 y 17 |
| tecnico | 1 | id, nombre_glpi (único), nombre_mostrar, turno, activo, incluir_en_ranking | Se crea automáticamente al importar; el coordinador completa el turno y el estado |
| kpi_definicion | 1 | id, codigo, nombre, descripcion, tipo_calculo, calculo_especial, filtro_numerador_json, filtro_denominador_json, campo_tiempo, unidad, direccion (MAYOR_MEJOR / MENOR_MEJOR / INFORMATIVO), umbral_verde, umbral_amarillo, meta, aproximado, critico, predefinido, visible_dashboard, orden, activo | KPI-00. `calculo_especial` identifica a los predefinidos que no caben en el motor genérico. `aproximado` muestra la marca "≈" |
| festivo | 1 | fecha (PK), descripcion | |
| parametro | 1 | clave (PK), valor, tipo (ENTERO / DECIMAL / TEXTO / BOOLEANO), grupo, descripcion, minimo, maximo | Umbrales editables en pantalla |
| usuario | 1 | id, nombre, perfil (COORDINADOR / CONSULTA), tecnico_id, pin_hash, activo, creado_en | **Todos** los usuarios tienen PIN con hash bcrypt |
| historial | 1 | id, entidad, entidad_id, accion, campo, valor_anterior, valor_nuevo, nota, usuario_id, fecha_hora | Solo inserción: triggers impiden UPDATE y DELETE |
| hallazgo | 2 | id, regla, severidad, entidad_tipo, entidad_valor, periodo, descripcion, datos_json, detectado_en, estado (NUEVO / REVISADO / DESCARTADO), comentario, revisado_por | HAL (reglas a revisar en la Fase 2) |
| snapshot | 2 | periodo (AAAA-MM o AAAA-Www), granularidad (MES / SEMANA), kpi_codigo, dimension_tipo, dimension_valor, valor, generado_en | Tendencias |
| segmov | 2 | — | **Pendiente de redefinir:** dependía de la estación, que ahora es solo informativa |
| seguimiento | 3 | id, ticket_id, fecha, autor, tipo (SEGUIMIENTO / TAREA / SOLUCION), privado, contenido, categoria_tarea, duracion_min, etiqueta | Opcional |
| criterio_calidad | 3 | id (PK), aplica_a, descripcion, como_verificar, critico, automatizable, regla | Semilla: `catalogos/criterios_calidad.csv` |
| evaluacion | 3 | id, ticket_id, tipo_caso, auditor_id, fecha, porcentaje, criticos_fallidos, resultado, retroalimentacion, version | Una evaluación vigente por ticket; las anteriores se conservan con su versión |
| evaluacion_detalle | 3 | evaluacion_id, criterio_id, resultado (C / N / NA), origen (MANUAL / AUTO / AUTO_CORREGIDO), nota | CAL-01 a CAL-03 |

**Tablas retiradas frente a la versión anterior:**

| Tabla | Motivo |
|---|---|
| ticket_grupo, grupo_escalamiento | No hay columna de grupo; el escalamiento es el estado "Escalado" |
| estacion_cat | La ubicación es solo informativa |
| categoria, causa, tipo_solucion | No hay columnas de Categoría ni de Solución. Los catálogos siguen en `spec/catalogos/`, por si se reincorporan con una migración |

**Índices:**
- `ticket(fecha_apertura)`, `ticket(tecnico_principal_id)`, `ticket(estado_codigo)`, `ticket(prioridad_nivel)`;
- `ticket_evento(tipo, fecha_evento)`, `ticket_evento(ticket_id)`;
- `ticket_cambio(ticket_id)`;
- `seguimiento(ticket_id, fecha)`;
- `hallazgo(estado, severidad)`;
- `snapshot(kpi_codigo, periodo)`.
