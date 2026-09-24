# 12 – Fases y criterios de aceptación

Una fase a la vez. Al cerrar cada una entrega lo indicado en `LEEME_PRIMERO.md` §2.8 y espera aprobación.

## Ajustes por la exportación real (2026-09-24)
La exportación de GLPI trae solo 10 columnas (ver `03`, IMP-00). Estas decisiones, tomadas con el coordinador, **prevalecen sobre cualquier referencia anterior** en los documentos `01`, `02`, `06`, `07`, `08`, `09` y `10`:

**Datos:**
- **Sin columnas de categoría, tipo, grupo, solución ni fechas de solución y cierre.** Las fechas de solución y cierre se aproximan con eventos detectados entre importaciones (IMP-06).
- **Escalado** = estado "Escalado" de GLPI. Los escalamientos se cuentan como eventos (RN-07).
- **Entidad y Ubicación** son solo informativas: no hay cliente, estación ni equivalencias de estaciones.

**Prioridades y turnos:**
- **Prioridades:** Mayor > Muy urgente > Urgente > Mediana > Baja > Muy baja. P1 = Mayor, según el parámetro `prioridad_p1`.
- **Objetivos de SLA:** uno por cada prioridad.
- **Turno de apertura:** franjas sin solape (mañana, tarde y nocturno). Día Intermedio es solo un turno asignable al técnico.

**Usuarios y avisos:**
- **Todos los usuarios tienen PIN** con hash bcrypt.
- **NOT-01:** el umbral de importación desactualizada es `dias_importacion_desactualizada`, con valor por defecto 1 día (se recomienda importar a diario).

**Dashboard (PAN-03):**
- "Top 10 estaciones" se reemplaza por **"Carga por técnico"** (abiertos por prioridad).
- "Distribución por familia" se reemplaza por **"Distribución por prioridad y estado"**.

**PAN-13 y asistente (PAN-01):**
- Sin equivalencias de estaciones, grupos de escalamiento ni catálogos de tipificación, causas o tipos de solución.
- El asistente pide: coordinador, franjas de turno, prioridad P1, objetivos de SLA por prioridad y umbrales de "sin actualizar".

**Decisiones al iniciar la Fase 2 (2026-09-24):**
- **Clasificación manual (IMP-07, nueva):** después de importar, el coordinador asigna a cada ticket **estación**, **categoría**, **causa** y **tipo de solución** con listas desplegables. La estación se elige de un catálogo de estaciones editable; categoría, causa y tipo de solución, de los catálogos de `spec/catalogos/`. La clasificación se guarda aparte: las reimportaciones nunca la modifican. Cada cambio queda en el historial.
- **Estación:** es la asignada a mano, no la columna Ubicación. Un botón opcional «Sugerir desde Ubicación» propone la estación cuyo nombre coincide con el último nivel de la ubicación; el coordinador confirma antes de guardar.
- **Caso repetido (HAL-01, KPI-11):** estación asignada + título normalizado (sin mayúsculas, tildes, números ni signos). Los tickets sin estación asignada no forman casos.
- **Tipificación (PAN-08, REP-04, HAL-03, KPI-09, KPI-10):** usan la categoría asignada a mano. KPI-09 y KPI-10 vuelven a la especificación con esa base. **HAL-09** avisa de los tickets resueltos sin clasificar.
- **SEGMOV (REP-08) y Estaciones (PAN-06, REP-02, HAL-02):** usan la estación asignada.
- **KPI-13** pasa a la Fase 3, porque necesita la importación de seguimientos.
**Decisiones al iniciar la Fase 3 (2026-09-24), tomadas por la IA con el visto bueno del coordinador para avanzar; revisables:**
- **G-02 y G-07 sí se precalifican**, con la clasificación manual (IMP-07):
  - G-02: estación y categoría asignadas (todas las del catálogo son hojas). La aplicación no se exporta, así que no se evalúa.
  - G-07: tipo de solución y causa asignados, o una nota de solución que empieza con `CAUSA: CAU-xx`.
- **CAL-06** compara la velocidad dentro de la misma **categoría asignada**. Los tickets sin categoría se comparan dentro de su prioridad.
- **E-02** (adjuntos) queda manual: la exportación no trae documentos. **E-03** se precalifica con el evento de escalamiento, porque no hay columna de grupo.
- **KPI-15** usa la fórmula de la spec 05 (60 % calidad + 40 % operativo), con los pesos en parámetros. **Falta confirmar con el coordinador** que coincide con la hoja KPI_SOPORTE.
- **CSV de seguimientos:** se importa con mapeo de columnas y perfil, igual que el de tickets. Los campos son los de `03`: ticket, fecha, autor, tipo, privado, contenido, categoría de tarea y duración. **Falta validar con una exportación real.**
- **El tipo de caso corregido en la evaluación** actualiza el tipo de caso del ticket (origen MANUAL) y se respeta al reimportar.
- **Resumen semanal por técnico:** cubre la última semana ISO completa y solo se genera para técnicos con tickets atendidos o evaluaciones en esa semana. El destinatario del `.eml` va vacío, porque la aplicación no guarda correos de técnicos; el coordinador lo completa en Outlook.
- **REP-06** es solo para el coordinador, como indica la spec 09. El usuario de consulta ve su propio histórico en la pantalla Calidad.
- **REP-11** incluye la evaluación vigente de cada ticket: porcentaje, resultado, críticos fallidos, fecha, versión y retroalimentación.

## Fase 1 – Importación, base y dashboard
**Incluye:**
- IMP-00 a IMP-06 (solo CSV de tickets).
- KPI-01 a KPI-08, KPI-16 y KPI-17 (predefinidos, con umbrales editables).
- RN-01 a RN-07.
- PAN-01, 02, 03, 04, 05 (sin seguimientos), 07 (sin calidad), 13 y 14.
- REP-01 y REP-03 en Excel y CSV.
- RNF-01 a RNF-04, 07, 09 a 11, 13 y 15.
- Generador de CSV ficticio con el formato de IMP-00, incluidas secuencias de archivos con cambios de estado.

**Criterios de aceptación:**
- **CA-01** El .exe corre en un PC con Windows limpio, sin internet.
- **CA-02** Importo un CSV con el formato real de IMP-00:
  - separador `;`, comillas y `;` al final de cada línea;
  - ID con separador de miles;
  - fechas `DD-MM-AAAA HH:MM`;
  - varios técnicos en una celda.

  La autodetección propone el mapeo de columnas, estados y prioridades; lo confirmo y lo guardo como perfil.
- **CA-03** Las filas con error (fecha inválida, ID vacío o no numérico, estado sin mapear) se muestran con su motivo y no se cargan; el resto sí.
- **CA-04** Reimportar el mismo archivo no duplica datos. Importar una versión posterior:
  - registra en `ticket_cambio` los cambios de estado, técnico y prioridad;
  - registra en `ticket_evento` los eventos ESCALAMIENTO, SOLUCION y REAPERTURA.

  Importar después un archivo más antiguo no hace retroceder los datos.
- **CA-05** `id_glpi`, `estado_codigo`, `prioridad_nivel`, `es_p1`, el técnico principal y los adicionales, `turno_apertura` y `horas_resolucion` se derivan bien en los casos de prueba de IMP-04.
- **CA-06** KPI-04 y KPI-05 coinciden con un cálculo manual sobre una secuencia de archivos ficticios, en la que un mismo ticket escalado 2 veces cuenta 2 escalamientos. El semáforo de KPI-05 respeta 20 % / 35 %.
- **CA-07** El dashboard carga en menos de 2 s con el CSV ficticio de volumen.
- **CA-08** Un usuario de consulta, que entra con su PIN, no ve las métricas de otros técnicos. El filtro se aplica en `core/`.

## Fase 2 – Análisis, hallazgos, SLA y reportes
**Incluye:**
- IMP-07 (clasificación manual) y la pantalla nueva **PAN-15 Clasificación**, con catálogos de estaciones, categorías, causas y tipos de solución.
- KPI-00 (editor de KPIs), KPI-09 a KPI-12 (sobre la clasificación manual). KPI-13 pasa a la Fase 3.
- PAN-06, 08, 09, 11 y 12.
- HAL-01 a HAL-12.
- SLA por ticket (CUMPLIDO / INCUMPLIDO / EN_RIESGO / SIN_OBJETIVO); REP-01 a REP-05, REP-08, REP-09 y REP-11 en PDF, Excel y CSV.
- Snapshot y tendencias.
- NOT-01 a NOT-03, NOT-05 y borradores .eml.
- RNF-05, RNF-06 y RNF-14.

**Criterios de aceptación:**
- **CA-09** Creo el KPI "% tickets REC sin CAUSA" (porcentaje; numerador familia = REC y sin causa; denominador familia = REC), con umbrales, y aparece en el dashboard con su semáforo.
- **CA-10** El caso de prueba de HAL-01 (4 tickets de la misma estación con el mismo título normalizado en la misma semana) genera el hallazgo con los 4 tickets. Reimportar no lo duplica.
- **CA-11** HAL-04 marca un ticket alta sin seguimiento hace 5 horas.
- **CA-12** SEGMOV reparte 100 horas entre 3 estaciones con 5, 3 y 2 casos → 50, 30 y 20; con casos 1, 1, 1 → la suma es exactamente 100 (ajuste de residuo).
- **CA-13** El PDF de REP-01 incluye filtros, fecha, usuario, gráficos y paginación.
- **CA-14** Al abrir la aplicación en un mes nuevo aparece NOT-03, y "Generar paquete mensual" produce el PDF, el Excel y el borrador .eml con el adjunto.
- **CA-15** Durante una importación grande la interfaz no se congela y muestra el progreso.
- **CA-23** Clasifico un ticket (estación, categoría, causa y tipo de solución), reimporto una versión posterior del CSV y la clasificación se conserva. El cambio aparece en el historial con el valor anterior y el nuevo.

## Fase 3 – Calidad de soporte
**Incluye:**
- CAL-01 a CAL-08, KPI-14 y KPI-15.
- PAN-10 completo; REP-06, REP-07 y REP-10 completo.
- NOT-04 y el resumen semanal .eml por técnico.
- Importación del CSV de seguimientos.

**Criterios de aceptación:**
- **CA-16** Al evaluar un ticket de tipo Escalamiento se muestran solo los 12 criterios generales y los 6 de escalamiento, como checkboxes tri-estado, con los críticos marcados.
- **CA-17** El caso de prueba de CAL-03 da 82 % "Por mejorar"; con un crítico fallido da "No conforme".
- **CA-18** Con seguimientos importados, G-07 y E-05 se precalifican. Corregir uno exige nota y queda como AUTO_CORREGIDO en el historial.
- **CA-19** La muestra semanal sugerida incluye todos los P1 y al menos un ticket por técnico en 2 semanas.
- **CA-20** El histórico semana a semana muestra flechas ▲▼ y % de variación correctos.
- **CA-21** El ranking excluye a los técnicos con menos de 10 tickets y solo lo ve el coordinador.
- **CA-22** Un técnico con tickets de categorías lentas no queda penalizado en velocidad frente a otro con categorías rápidas: prueba con datos ficticios que verifica la normalización de CAL-06.

## Fase 4 (futura) – API REST de GLPI
Implementar `fuente_api.py` con la misma interfaz. No se desarrolla hasta que se apruebe.

## Entregables por fase
- Código completo.
- `build.bat` y el .exe.
- Pruebas y su resultado.
- README.
- MANUAL_USUARIO actualizado.
- Requisitos y CA cubiertos.
- Pendientes y riesgos.
