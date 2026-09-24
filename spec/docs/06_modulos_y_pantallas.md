# 06 – Módulos y pantallas (PySide6)

## Estilo
- **Estética:** corporativa, tema claro, azul marino como color principal, tipografía Segoe UI.
- **Ventana principal:** menú lateral izquierdo con íconos y barra superior con:
  - selector de período (semana / mes / rango);
  - filtros globales (cliente, turno);
  - fecha de la última importación, en rojo si tiene más de 7 días;
  - campana de alertas.
- **Tablas:** con orden, filtro por columna, búsqueda y botón "Exportar" (Excel / CSV).
- **Gráficos:** matplotlib embebido (FigureCanvasQTAgg). Las mismas figuras se reutilizan en los PDF.
- **Colores de semáforo:** siempre con texto o ícono (✔ ▲ ✖).

## Pantallas
| ID | Pantalla | Contenido |
|---|---|---|
| PAN-01 | Inicio de sesión | Selección de usuario; PIN para el coordinador. En la primera ejecución, asistente de configuración: coordinador, franjas de turnos, grupos de escalamiento. |
| PAN-02 | Importar | Elegir archivo → autodetección → mapeo de columnas con perfil guardado → vista previa con validación → importar → resumen. Historial de importaciones. |
| PAN-03 | Dashboard | Tarjetas de KPIs visibles (valor, variación frente al período anterior, semáforo). Semáforo de criticidad global. Gráficos: tickets por semana (recibidos vs. resueltos), backlog en el tiempo, distribución por familia, top 10 estaciones, brecha frente a la meta por KPI (barras de valor vs. meta). Panel "Hallazgos nuevos". |
| PAN-04 | Novedades | Tickets recientes y abiertos con filtros por estado, técnico, prioridad, estación y familia. Accesos rápidos: "sin seguimiento > plazo", "resueltos sin cerrar", "P1 abiertos", "escalados > 5 días". Doble clic abre el detalle. |
| PAN-05 | Detalle de ticket | Datos, cambios detectados (`ticket_cambio`), línea de tiempo de seguimientos con sus etiquetas, causa y evaluación de calidad (si existe). Botón "Evaluar calidad". |
| PAN-06 | Estaciones | Ranking por volumen, reincidencia y tiempo de resolución. Detalle: tendencia semanal, familias más frecuentes y casos repetidos (HAL-01). Mapa de calor estación × familia. |
| PAN-07 | Responsables | Por técnico: carga actual (abiertos por prioridad), atendidos por semana, mediana de resolución y de primera respuesta, SLA individual, resueltos sin cerrar, reaperturas y calidad. La vista de consulta muestra solo las métricas propias. |
| PAN-08 | Tipificaciones | Distribución por familia y categoría (barras y árbol), tendencia mensual por familia, categorías que crecen (variación frente al promedio de 3 meses), uso de OTR-01 y categorías no hoja. |
| PAN-09 | Hallazgos | Lista de hallazgos (HAL) con severidad, fecha, entidad y estado. Acciones: marcar revisado o descartado con comentario, y abrir los tickets relacionados. |
| PAN-10 | Calidad de soporte | Pestañas: (1) Evaluar tickets con checkboxes (CAL-01); (2) Histórico por técnico semana a semana (CAL-05); (3) Rendimiento (CAL-06); (4) Panel comparativo y ranking, solo coordinador (CAL-07); (5) Incumplimiento por criterio (CAL-08). |
| PAN-11 | KPIs | Lista de KPIs y editor visual (KPI-00) con vista previa del valor. |
| PAN-12 | Reportes | Catálogo de reportes (REP), filtros, vista previa y exportar Excel/PDF/CSV. Botones "Generar paquete mensual" y "Borrador de correo". |
| PAN-13 | Configuración | Parámetros y umbrales, franjas de turno, grupos de escalamiento, técnicos (turno, activo, incluir en ranking), equivalencias de estaciones, festivos, usuarios, catálogos (tipificación, causas, criterios), respaldos. |
| PAN-14 | Historial | Auditoría de cambios manuales, solo lectura. |

## Boceto del dashboard
```
┌ Período: [Sep 2026 ▼]  Cliente: [Todos ▼]  Última importación: 23/09 07:40   🔔3 ┐
│ [Recibidos 212 ▲4%] [Gestionados 91% ✔] [Escalam. 24% ▲] [SLA 87% ▲] [Sin cerrar 9% ✖] │
│ Criticidad global:  ▲ AMARILLO                                                       │
│ ┌ Recibidos vs resueltos por semana ┐ ┌ Backlog ┐ ┌ Por familia ┐                   │
│ └───────────────────────────────────┘ └─────────┘ └─────────────┘                   │
│ ┌ Top 10 estaciones ┐ ┌ Brecha vs meta por KPI ┐ ┌ Hallazgos nuevos ┐               │
└──────────────────────────────────────────────────────────────────────────────────────┘
```
