# 08 – Hallazgos automáticos

**Cuándo se ejecutan:** después de cada importación y bajo demanda. Cada regla genera registros en `hallazgo`.

**Reglas generales:**
- **Sin duplicados:** un hallazgo abierto con la misma regla, entidad y período no se duplica; se actualizan sus datos.
- **Umbrales:** todos en la tabla `parametro`.

## HAL-01 – Caso repetido (cuántas veces sale un caso por semana y por mes)
- **Clave del "caso":** `codigo_categoria + estacion` por defecto. Opciones configurables: solo `codigo_categoria`, o `codigo_categoria + estacion + aplicacion`.
- **Conteo:** por **semana ISO** y por **mes**.
- **Alertas:**
  - Semana: ≥ `rep_semana_umbral` (3) → severidad MEDIA; ≥ 5 → ALTA.
  - Mes: ≥ `rep_mes_umbral` (5) → MEDIA; ≥ 8 → ALTA.
- **Salidas:**
  - tabla "Casos repetidos" con clave, conteo semana, conteo mes, tendencia (▲▼ frente al período anterior) y tickets relacionados;
  - recomendación automática: "Evaluar Problema en GLPI / runbook / automatización".
- *Caso de prueba:* 4 tickets `DAT-01` en la estación X entre lunes y domingo de la misma semana → hallazgo MEDIA con 4 tickets relacionados.

## HAL-02 – Pico por estación
Tickets de una estación en la semana > media de sus últimas 8 semanas + 2 desviaciones estándar, y al menos 5 tickets → ALTA.

## HAL-03 – Categoría en crecimiento
Tickets de una categoría en el mes ≥ 1,5 × el promedio de los 3 meses anteriores, y al menos 5 tickets → MEDIA.

## HAL-04 – Sin seguimiento
Ticket abierto cuya última actualización (o último seguimiento) supera el umbral de su prioridad (P1 1 h; alta 4 h; media/baja 24 h) → ALTA para P1 y alta; MEDIA para el resto.

## HAL-05 – Resuelto sin cerrar
Resuelto hace más de `dias_resuelto_sin_cerrar` (2) → BAJA. Se agrupa por técnico: "Técnico X tiene N resueltos sin cerrar".

## HAL-06 – Escalado estancado
Escalado y abierto hace más de `dias_escalado_alerta` (5) → MEDIA; más de 10 → ALTA.

## HAL-07 – P1 abierto
Cualquier ticket de prioridad máxima abierto → ALTA (se cierra el hallazgo solo cuando el ticket se resuelve).

## HAL-08 – Sobrecarga de técnico
Tickets abiertos del técnico > P90 del equipo y > 1,5 × la mediana del equipo → MEDIA.

## HAL-09 – Datos incompletos
Tickets resueltos sin categoría hoja, sin CAUSA o sin tipo de solución → BAJA, agrupado por técnico y semana.

## HAL-10 – Semáforo en rojo
Un KPI crítico pasa a rojo en el período → ALTA.

## HAL-11 – Reapertura
Ticket reabierto (cambio Resuelto/Cerrado → abierto) → MEDIA.

## HAL-12 – Importación desactualizada
Última importación con más de 7 días → aviso al iniciar (NOT-01).

## Presentación
- **Dashboard:** panel con los hallazgos NUEVOS por severidad.
- **PAN-09:** lista completa con filtro por estado, severidad, regla y período.
- **Reportes:** en el reporte mensual, resumen de hallazgos del mes por regla y los 5 casos más repetidos.
