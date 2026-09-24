# 02 – Glosario

| Término | Definición |
|---|---|
| Ticket | Caso de GLPI (incidencia o solicitud), identificado por su ID de GLPI. |
| Familia | Primer nivel de la tipificación (APL, CAR, EQP, RED, BDD, ACC, DAT, REC, REP, CFG, ACT, OTR). |
| Código de categoría | Prefijo de la categoría hoja (p. ej. `REC-03.1`), extraído del nombre de la categoría. |
| Cliente / Estación | Se derivan de la Ubicación de GLPI (Cliente > [Proyecto] > Estación). |
| Técnico | Responsable asignado en GLPI ("Asignado a – Técnico"). |
| Grupo de escalamiento | Grupo asignado que representa otra área: Análisis y Diseño, Desarrollo, Laboratorio, Pruebas, Redes, Soporte N3 (lista configurable). |
| Escalado | Ticket con un grupo de escalamiento asignado o con la etiqueta `[ESC]`. |
| Gestionado | Ticket cerrado o escalado. |
| Resuelto sin cerrar | Ticket en estado Resuelto con fecha de solución más antigua que el umbral configurado. |
| Turno | Mañana, Día Intermedio, Tarde o Nocturno. Se deriva de la hora según las franjas de `config.ini`. |
| Tipo de caso | Gestión, Escalamiento, Solicitud, Crítico P1, En espera externa, Cambio/despliegue, Actividad programada (estándar de documentación). |
| Etiqueta | Marca al inicio de una nota: `[DIAG]`, `[ESC]`… |
| Evaluación de calidad | Revisión de un ticket con los criterios que aplican a su tipo de caso: checkboxes cumple / no cumple / no aplica. |
| Criterio crítico | Criterio cuyo incumplimiento hace "No conforme" al ticket, sin importar el porcentaje. |
| KPI | Indicador con fórmula, meta y semáforo. Puede ser predefinido o creado por el usuario. |
| Hallazgo | Alerta generada automáticamente por una regla HAL. |
| Caso repetido | Mismo código de categoría en la misma estación (clave configurable) varias veces en una ventana de tiempo. |
| SEGMOV | Distribución mensual proporcional de un total de horas entre estaciones, según su número de casos. |
| Snapshot | Foto mensual de los KPIs para ver tendencias. |
