# 09 – Reportes, SLA y notificaciones

**Todos los reportes:**
- **Filtros:** período y filtros globales.
- **Formatos:** Excel (openpyxl, con tablas y gráficos como imagen), PDF (fpdf2, con encabezado, filtros, fecha, usuario y paginación) y CSV (pandas).
- **Ubicación:** `exportaciones/AAAA-MM/`.

## Reportes
| ID | Reporte | Contenido | Perfil |
|---|---|---|---|
| REP-01 | Resumen de indicadores | Todos los KPIs visibles con valor, meta, semáforo y variación frente al período anterior; gráfico de brechas vs. meta | Todos |
| REP-02 | Estaciones | Ranking por volumen, reincidencia y tiempo; familias por estación; casos repetidos | Todos |
| REP-03 | Responsables – operativo | Carga, atendidos, tiempos, SLA, resueltos sin cerrar y reaperturas por técnico | Coordinador (cada técnico ve el suyo) |
| REP-04 | Tipificaciones | Distribución, tendencia por familia, categorías en crecimiento, OTR-01, no hojas | Todos |
| REP-05 | Hallazgos | Hallazgos del período por regla y severidad, estado de revisión y casos repetidos | Todos |
| REP-06 | Calidad de soporte – histórico | Por técnico, semana a semana: atendidos, % documentación, tiempos (subidas y bajadas) | Coordinador |
| REP-07 | Calidad de soporte – comparativo | Ranking CAL-07, radar, incumplimiento por criterio (CAL-08) | Solo coordinador |
| REP-08 | Distribución de horas SEGMOV | Horas mensuales totales (dato de entrada) repartidas proporcionalmente entre las estaciones marcadas `incluir_segmov`, según sus casos del mes. horas_estación = REDONDEAR(total × casos_estación / casos_total, 1). La diferencia de redondeo se ajusta en la estación con mayor residuo para que la suma sea exacta. Tabla y gráfico | Coordinador |
| REP-09 | SLA | Cumplimiento por prioridad, cliente, técnico y familia; tickets fuera de SLA con detalle; tendencia de 6 meses | Todos |
| REP-10 | Paquete mensual gerencial | Un PDF y un Excel con: resumen ejecutivo (texto editable antes de exportar), REP-01, REP-09, tendencias de 6 meses (snapshot), top 5 casos repetidos, hallazgos, calidad del área (KPI-14/15), SEGMOV y plan de mejora (campo editable) | Coordinador |
| REP-11 | Datos para auditoría | Exportación de tickets con campos derivados y evaluaciones, para revisión externa o el libro de control | Coordinador |

## SLA
- **Objetivo por ticket:**
  1. `fecha_vencimiento` de GLPI si existe;
  2. si no, objetivo en horas por prioridad (parámetros `sla_horas_muy_alta`, `sla_horas_alta`, `sla_horas_media`, `sla_horas_baja`; valores iniciales a definir por el coordinador en el asistente de configuración: la aplicación no debe asumirlos).
- **Estado SLA** por ticket: CUMPLIDO / INCUMPLIDO / EN_RIESGO (abierto con ≥ 80 % del objetivo consumido) / SIN_OBJETIVO.
- **SLA individual:** el mismo cálculo filtrado por técnico principal.

## Snapshot y tendencias
- **Cuándo:** al importar datos de un mes o una semana cerrados (o con el botón "Generar snapshot"), se guarda el valor de cada KPI activo en `snapshot`: global, por cliente, por técnico y por familia.
- **Uso:** las tendencias de 6 y 12 meses y el histórico semanal salen de esta tabla.
- **Sin duplicados:** regenerar un período reemplaza el anterior y queda en el historial.

## Notificaciones (aplicación offline)
| ID | Alerta | Cuándo |
|---|---|---|
| NOT-01 | Importación desactualizada (> 7 días) | Al iniciar |
| NOT-02 | Hallazgos nuevos de severidad ALTA | Al iniciar y después de importar |
| NOT-03 | Paquete mensual pendiente (mes anterior sin generar) | Primer inicio del mes |
| NOT-04 | Evaluaciones de calidad de la semana pendientes | Lunes |
| NOT-05 | KPI crítico en rojo | Después de importar |

### Borradores de correo (.eml)
- **Tipos:**
  - paquete mensual (PDF adjunto) para jefatura;
  - resumen semanal para cada técnico con **sus propias** métricas y retroalimentación (nunca el ranking de otros);
  - reporte de hallazgos ALTA.
- **Formato:** el .eml se abre en el cliente de correo predeterminado (Outlook) para revisar y enviar. No se guardan contraseñas ni se envía nada automáticamente.
