# 03 – Fuente de datos e importación

> **Ajuste del 2026-09-24.** Este documento se reescribió según el formato real de la exportación de GLPI, confirmado por el coordinador. La exportación trae **solo 10 columnas**: no incluye Categoría, Tipo, Grupo asignado, Fecha de solución, Fecha de cierre ni Solución. Las reglas que dependían de esas columnas se retiraron o se reemplazaron por eventos detectados entre importaciones (IMP-06).

## Fuentes
| Fuente | Obligatoria | Cómo se obtiene |
|---|---|---|
| **CSV de tickets** | Sí | Búsqueda de tickets en GLPI 9.1.4 → exportar CSV. Siempre trae las 10 columnas de IMP-00 |
| **CSV de seguimientos y tareas** | No (habilita los criterios automáticos de calidad; Fase 3) | Exportación de seguimientos y tareas: una fila por nota. Si GLPI solo la entrega como columna multivalor dentro del CSV de tickets, soportarla con un separador configurable |
| **API REST de GLPI** | Futuro | Interfaz `core/fuentes/fuente_api.py` con el mismo contrato que `fuente_csv.py` |

## IMP-00 – Formato real de la exportación
Ejemplo con datos ficticios, tal como queda en el archivo (visto con un editor de texto, no con Excel):
```
"ID";"Título";"Entidad";"Estado";"Autor - Autor";"Asignado a: - Técnico";"Fecha de Apertura";"Última actualización";"Prioridad";"Ubicación";
"346 649";"TITULO DE NOVEDAD";"Grupo > Empresa > Seccional > Departamento (TI) > Área";"En curso (asignada)";"Autor 1";"Tecnico 1";"06-04-2026 05:21";"22-09-2026 14:22";"Mediana";"Departamento (TI) > Filial > Cliente > Estación";
```
- **Separador y comillas:** separador `;` y todos los campos entre comillas dobles.
- **Punto y coma final:** cada línea termina en `;`, lo que genera una columna vacía extra. Esa columna se descarta.
- **Codificación:** se autodetecta entre UTF-8, UTF-8 con BOM y Latin-1.
- **ID:** texto con separador de miles (`"346 649"`), que puede ser un espacio, un espacio duro (U+00A0) o un espacio fino (U+202F). Se eliminan los separadores; si quedan caracteres que no son dígitos, es un error.
- **Fechas:** `DD-MM-AAAA HH:MM`. También se aceptan `DD/MM/AAAA H:MM` y `AAAA-MM-DD HH:MM`, por si cambia la exportación.
- **Varios técnicos:** uno por línea dentro de la misma celda entre comillas. Las líneas vacías se descartan.
- **Estados observados:** Nuevo, En curso (asignada), En curso (planificada), En espera, **Escalado** (estado propio de esta instalación), Resueltas y Cerrado.
- **Prioridades, de mayor a menor:** Mayor, Muy urgente, Urgente, Mediana, Baja y Muy baja.
- **Entidad y Ubicación:** rutas jerárquicas separadas por `>`, con espaciado irregular. **Son solo informativas:** se guardan y se muestran, pero no se usan en reglas ni en KPIs.

## IMP-01 – Mapeo de columnas
- **Pantalla de mapeo:** asocia cada columna del CSV a un **campo interno**. Se guarda como "perfil de importación" reutilizable.
- **Autodetección:** propone el mapeo con los encabezados de IMP-00, además del separador, la codificación y el formato de fecha. El usuario confirma el resultado.
- **Mapeo de estados y prioridades:** el perfil incluye el mapeo editable de los textos de estado a `estado_codigo` y de los textos de prioridad a `prioridad_nivel`, precargado con los valores de IMP-00.

**Campos internos del ticket:**

| Campo interno | Columna de GLPI | Obligatorio | Nota |
|---|---|---|---|
| id_glpi | ID | Sí | Entero; clave |
| titulo | Título | Sí | |
| entidad | Entidad | No | Informativo |
| estado | Estado | Sí | Se normaliza a `estado_codigo` |
| autor | Autor - Autor | No | Dato personal (IMP-05) |
| tecnico | Asignado a: - Técnico | Sí (la columna) | Varios valores posibles; puede estar vacío si el ticket no tiene técnico asignado |
| fecha_apertura | Fecha de Apertura | Sí | |
| ultima_actualizacion | Última actualización | Sí | Es la fecha que se asigna a los eventos (IMP-06) |
| prioridad | Prioridad | Sí | Se normaliza a `prioridad_nivel` |
| ubicacion | Ubicación | No | Informativo |

**Códigos de estado (`estado_codigo`):** NUEVO, EN_CURSO_ASIGNADO, EN_CURSO_PLANIFICADO, EN_ESPERA, ESCALADO, RESUELTO y CERRADO. Un ticket **abierto** es el que no está en RESUELTO ni en CERRADO.

**Niveles de prioridad (`prioridad_nivel`):** Mayor = 6, Muy urgente = 5, Urgente = 4, Mediana = 3, Baja = 2 y Muy baja = 1. Un ticket es **P1** si su nivel es mayor o igual al parámetro `prioridad_p1`, que por defecto es 6 (Mayor).

**Campos del CSV de seguimientos (Fase 3):** ticket_id, fecha, autor, tipo (seguimiento / tarea / solución), privado, contenido, categoría de tarea y duración.

## IMP-02 – Validación antes de guardar
- **Errores (en rojo; la fila no se carga):**
  - ID vacío, no numérico o duplicado dentro del archivo;
  - fecha de apertura o de última actualización vacía o inválida;
  - estado o prioridad sin mapeo en el perfil. El motivo indica el valor que hay que mapear.
- **Advertencias (en amarillo; la fila se carga):**
  - ticket sin técnico asignado;
  - última actualización anterior a la fecha de apertura.
- **Vista previa:** filas válidas en verde, con advertencia en amarillo y con error en rojo, cada una con su motivo.
- **Botón "Importar filas válidas".** Las filas con error no se cargan y se pueden exportar a CSV para corregirlas.
- **Lectura y transacción:** lectura por bloques (`chunksize`) y transacción única por archivo. Si algo falla, no queda nada a medias.

## IMP-03 – Importación incremental e historial de cambios
- **Clave:** `id_glpi`. Si el ticket ya existe, se actualiza.
- **Orden de los archivos:** si la fila trae una última actualización **anterior o igual** a la guardada, no se actualiza. Así, importar un archivo viejo después de uno nuevo no hace retroceder los datos.
- **Historial de cambios:** por cada ticket actualizado se guardan en `ticket_cambio` los cambios de **estado, técnico y prioridad** frente a la importación anterior.
- **Eventos:** los cambios de estado generan eventos según IMP-06.
- **Duplicados:** si se importa dos veces el mismo archivo (mismo hash), el sistema avisa y no duplica nada.
- **Registro:** cada importación queda en `importacion` con archivo, hash, fecha, usuario, filas leídas, válidas, con advertencia y con error, y el rango de fechas que contiene.
- **Frecuencia recomendada:** diaria (ver IMP-06, "Límite").

## IMP-06 – Eventos detectados entre importaciones
Como el CSV solo trae el **estado actual**, los eventos se detectan comparando el estado guardado con el de la nueva importación. Cada evento se guarda en `ticket_evento`.

**La fecha del evento** es la "Última actualización" de la fila en la que se detecta. El evento guarda además el técnico principal de ese momento.

| Evento | Estado anterior → estado nuevo |
|---|---|
| ESCALAMIENTO | Cualquier estado distinto de ESCALADO → ESCALADO |
| SALIDA_ESCALADO | ESCALADO → cualquier otro estado |
| SOLUCION | Abierto → RESUELTO o CERRADO |
| CIERRE | Distinto de CERRADO → CERRADO |
| REAPERTURA | RESUELTO o CERRADO → abierto |

- **Paso de RESUELTO a CERRADO:** genera solo CIERRE. La gestión de soporte ya se contó con SOLUCION.
- **Ticket visto por primera vez:** se registran los eventos de su estado actual con `origen = PRIMERA_VEZ`:
  - ESCALADO → ESCALAMIENTO;
  - RESUELTO → SOLUCION;
  - CERRADO → SOLUCION y CIERRE.

  En la primera carga histórica, estos eventos se marcan como "histórico aproximado". Los detectados entre importaciones llevan `origen = TRANSICION`.
- **Fechas aproximadas del ticket:**
  - `fecha_solucion` = fecha del último evento SOLUCION;
  - `fecha_cierre` = fecha del último evento CIERRE;
  - una REAPERTURA borra ambas hasta la siguiente solución.
- **Límite:** si un ticket cambia varias veces entre dos importaciones (por ejemplo, se escala y vuelve), solo se ve el cambio neto. Por eso:
  - se recomienda importar **a diario**;
  - el aviso de importación desactualizada usa el parámetro `dias_importacion_desactualizada`, con valor por defecto 1.

## IMP-04 – Campos derivados (al importar)
| Derivado | Regla |
|---|---|
| id_glpi | Se eliminan los separadores de miles del ID (IMP-00) |
| estado_codigo | Mapeo del perfil (IMP-01) |
| prioridad_nivel, es_p1 | Mapeo del perfil; `es_p1` = nivel ≥ `prioridad_p1` |
| tecnico_principal | Primer técnico de la celda. Los demás se guardan en `ticket_tecnico`. El técnico se crea en la tabla `tecnico` si no existe |
| escalado | Estado actual = ESCALADO. El histórico de escalamientos está en `ticket_evento` |
| fecha_solucion, fecha_cierre | Aproximadas, según IMP-06 |
| horas_resolucion | (fecha_solucion − fecha_apertura) en horas. Es aproximada. No hay columna de tiempo de espera, así que no se descuenta (RN-03) |
| horas_hasta_cierre | (fecha_cierre − fecha_apertura) en horas. Es aproximada |
| resuelto_sin_cerrar | **No se guarda**; se calcula al consultar: estado RESUELTO y fecha de corte − fecha_solucion > `dias_resuelto_sin_cerrar` |
| turno_apertura | Hora de apertura según las franjas de apertura de `config.ini` `[turnos]`. **Deben ser franjas sin solape que cubran las 24 h** (mañana, tarde y nocturno). "Día Intermedio" es solo un turno asignable al técnico, no una franja de apertura |
| tipo_caso | Inferido: Crítico P1 si `es_p1`; Escalamiento si tiene algún evento ESCALAMIENTO; si no, Gestión. El usuario puede corregirlo en la evaluación (Fase 3); la corrección manual no se sobrescribe al reimportar |

**Derivados retirados, porque no hay columna de origen:** codigo_categoria, familia, es_hoja, cliente, estacion, causa_codigo y tiene_tipo_solucion. Si en el futuro la exportación incluye Categoría, Solución, Tipo de solución, Grupo asignado o fechas de solución y cierre, se reincorporan con una migración.

## IMP-05 – Datos personales
- El CSV trae nombres de autores y técnicos.
- Se guardan localmente y **nunca** se envían a servicios externos.
- Hay una opción "anonimizar autor" en las exportaciones compartidas.
