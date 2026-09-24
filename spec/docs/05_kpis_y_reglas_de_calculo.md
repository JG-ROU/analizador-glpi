# 05 – KPIs y reglas de cálculo

> **Ajuste del 2026-09-24.** KPIs adaptados a la exportación real de 10 columnas (ver `03`):
> - KPI-04 y KPI-05 se calculan con **eventos** (definición del coordinador).
> - KPI-09 y KPI-10 se retiran, porque no hay categoría ni solución.
> - Se agregan KPI-16 y KPI-17.

## Reglas generales de cálculo
- **RN-01 – Período.** Todos los KPIs se calculan para un período (semana ISO, mes o rango) y admiten filtros por técnico, turno, prioridad, estado y tipo de caso. Desde la Fase 2 también por la clasificación manual (IMP-07): estación, cliente, familia, categoría y causa. Entidad y Ubicación no son filtros de KPI; son solo informativas.
- **RN-02 – Mediana, no promedio.** Los tiempos se reportan con **mediana** (y P90 como dato secundario), porque unos pocos casos largos distorsionan el promedio. Cuando el usuario lo pida, también se muestra el promedio.
- **RN-03 – Tiempo de espera.** La exportación no trae tiempo de espera. Los reportes de tiempos indican siempre "Tiempos sin descontar espera".
- **RN-04 – Muestra mínima.** Un indicador calculado sobre menos de `muestra_minima` (10) tickets se muestra con el ícono "⚠ muestra pequeña" y no entra en rankings.
- **RN-05 – Días hábiles.** Donde aplique se excluyen fines de semana y la tabla `festivo`. La operación es 24/7, así que los SLA de tickets usan horas calendario salvo configuración contraria.
- **RN-06 – Valores aproximados.** Los KPIs basados en eventos de solución o de escalamiento (IMP-06) usan la "Última actualización" como fecha del evento. Los que dependen de la **duración** entre fechas (KPI-06, KPI-07 y KPI-17) se muestran con la marca "≈ aproximado" y una nota que lo explica.
- **RN-07 – Gestiones.** Una **gestión** es un evento SOLUCION o un evento ESCALAMIENTO (IMP-06):
  - **se cuentan eventos, no tickets:** un ticket escalado 2 veces y resuelto suma 3 gestiones;
  - **se cuentan en el período en que ocurre el evento**, sin importar cuándo se abrió el ticket;
  - el paso de Resuelto a Cerrado no es una gestión adicional.

## KPI-00 – KPIs configurables (el usuario puede crearlos)
Todo KPI, predefinido o creado, se define en `kpi_definicion` con:

| Elemento | Opciones |
|---|---|
| Tipo de cálculo | CONTEO · PORCENTAJE (numerador / denominador) · MEDIANA_TIEMPO · PROMEDIO_TIEMPO · P90_TIEMPO · CONTEO_EVENTOS (por tipo de evento) |
| Filtros (numerador y denominador) | Condiciones combinables con Y: estado, prioridad (nivel o lista), es P1, técnico, turno, escalado actualmente (sí/no), tuvo escalamiento, resuelto (sí/no), reabierto, tipo de caso, rango de horas de resolución; y de la clasificación manual: estación, cliente, familia, código de categoría (lista o prefijo), causa, tiene causa, clasificado (sí/no); tiene etiqueta X (Fase 3) |
| Campo de tiempo | horas_resolucion · horas_hasta_cierre · horas_en_escalado · horas_primera_respuesta (requiere seguimientos) |
| Semáforo | dirección (mayor es mejor / menor es mejor / informativo), umbral verde, umbral amarillo y meta opcional |
| Presentación | visible en dashboard (sí/no), orden, unidad, descripción, crítico (sí/no) |

- **Editor visual:** el editor de KPIs (PAN-11) construye los filtros con listas desplegables. **No se evalúa código escrito por el usuario:** los filtros se guardan como JSON y se traducen a consultas parametrizadas.
- **Vista previa:** el editor muestra el valor del KPI en el período actual.
- **Predefinidos:** los KPIs predefinidos no se pueden borrar; solo cambiar sus umbrales, visibilidad, orden y marca de crítico. Los que no caben en el motor genérico se implementan con `calculo_especial`.

## KPIs predefinidos
| Código | Nombre | Fórmula | Semáforo inicial |
|---|---|---|---|
| KPI-01 | Tickets recibidos | Conteo de tickets con fecha_apertura en el período | Informativo |
| KPI-02 | Tickets resueltos | Tickets distintos con un evento SOLUCION en el período | Informativo |
| KPI-03 | Backlog al corte | Tickets abiertos antes del corte cuyo último evento de solución o reapertura anterior al corte no es una solución (IMP-06). Sirve igual para el corte actual y para cortes pasados | Menor es mejor; umbrales a definir con la línea base |
| KPI-04 | Total gestionados | (eventos SOLUCION + eventos ESCALAMIENTO del período) / tickets recibidos en el período × 100. **Puede superar 100 %** | Meta 100 %; ≥ 80 % verde; < 80 % activa acción preventiva |
| KPI-05 | Tasa de escalamiento | Eventos ESCALAMIENTO / (eventos SOLUCION + eventos ESCALAMIENTO) del período × 100 | ≤ 20 % verde · 20–35 % amarillo · > 35 % rojo |
| KPI-06 | Tiempo de resolución ≈ | Mediana de horas_resolucion (y P90) de los tickets resueltos en el período, por prioridad | Umbrales por prioridad en parámetros |
| KPI-07 | Cumplimiento SLA ≈ | Resueltos a tiempo / resueltos con objetivo × 100. "A tiempo" = horas_resolucion ≤ objetivo de su prioridad (`sla_horas_<prioridad>`, uno por cada uno de los 6 niveles). No hay fecha de vencimiento en la exportación | ≥ 90 % verde · 80–90 % amarillo (propuesta) |
| KPI-08 | Resueltos sin cerrar | De los tickets resueltos en el período, los que a la fecha de corte siguen en Resuelto (sin cierre ni reapertura) desde hace más de `dias_resuelto_sin_cerrar` / tickets resueltos en el período × 100. Así el valor nunca supera 100 %. El cierre depende del visto bueno del autor: **en la vista por técnico es informativo, no una falla del técnico** | ≤ 5 % verde (propuesta) |
| KPI-09 | Completitud de clasificación (Fase 2) | Tickets resueltos en el período con estación, categoría, causa y tipo de solución asignados a mano (IMP-07) / tickets resueltos en el período × 100 | ≥ 95 % verde (propuesta) |
| KPI-10 | Uso de "Otros" (Fase 2) | Tickets con categoría OTR-01 / tickets con categoría asignada × 100 (el denominador excluye los no clasificados) | ≤ 5 % verde |
| KPI-11 | Reincidencia (Fase 2) | Tickets recibidos en el período cuyo "caso" (estación asignada + título normalizado, HAL-01) tiene otro ticket en los 7 días anteriores / tickets recibidos con estación asignada × 100 | Menor es mejor; umbrales tras la línea base |
| KPI-12 | Reaperturas | Eventos REAPERTURA del período / tickets resueltos en el período × 100 | ≤ 5 % verde (propuesta) |
| KPI-13 | Tiempo de primera respuesta | **Pasa a la Fase 3** (requiere la importación de seguimientos) | Por prioridad |
| KPI-14 | Calidad de documentación | Promedio del % de las evaluaciones del período | ≥ 90 % verde · 70–90 % amarillo |
| KPI-15 | Índice general del área | 60 % calidad + 40 % operativo. Calidad = KPI-14. Operativo = promedio de KPI-04 (con tope de 100 para este índice), KPI-07 y (100 − KPI-08), todos en escala 0–100 | ≥ 85 verde · 70–85 amarillo (propuesta) |
| KPI-16 | Tickets sin actualizar | Tickets abiertos cuya (fecha de corte − ultima_actualizacion) supera el umbral de su prioridad (`horas_sin_actualizar_<prioridad>`) / tickets abiertos × 100. Umbrales iniciales, tomados de HAL-04 y editables: Mayor 1 h; Muy urgente y Urgente 4 h; Mediana, Baja y Muy baja 24 h | Menor es mejor; umbrales tras la línea base |
| KPI-17 | Tiempo en escalado ≈ | Mediana de horas entre cada evento ESCALAMIENTO y su SALIDA_ESCALADO, para las salidas ocurridas en el período | Menor es mejor; umbrales tras la línea base |

- **Umbrales:** todos son editables. Los marcados "propuesta" se deben ajustar con la línea base del primer mes.
- **Objetivos de SLA:** los valores iniciales los define el coordinador en el asistente de configuración. La aplicación no los asume.
- **Pregunta abierta para la IA (Fase 3):** los componentes exactos de KPI-15 deben coincidir con la hoja KPI_SOPORTE del libro de control del coordinador; confirma con el usuario antes de implementarlo.

## Semáforo de criticidad (dashboard)
- **Colores:** verde, amarillo y rojo según la dirección y los umbrales, siempre con ícono y texto además del color.
- **Criticidad global del período:** peor semáforo entre los KPIs marcados como "críticos" (configurable; por defecto KPI-04, KPI-05, KPI-07 y KPI-08).
