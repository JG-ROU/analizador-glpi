# Manual de usuario – Analizador GLPI (Fases 1 a 3)

## 1. Instalación

1. Copie la carpeta `AnalizadorGLPI` a su equipo o a una memoria USB. No requiere instalación ni permisos de administrador.
2. Abra `AnalizadorGLPI.exe`.
3. En el primer arranque se crean junto al ejecutable:

| Elemento | Contenido |
|---|---|
| `config.ini` | Configuración de arranque: rutas, franjas de turno, nivel de registro y retención de respaldos |
| `data\analizador.db` | Base de datos con toda la información |
| `data\respaldos\` | Copias de seguridad automáticas |
| `logs\app.log` | Registro técnico de errores |
| `exportaciones\` | Reportes, tablas exportadas y borradores de correo, por mes |

El aplicativo funciona sin internet. Los datos quedan solo en este equipo.

## 2. Primera ejecución: asistente de configuración

El asistente pide:

1. **Coordinador:** su nombre y un PIN de 4 a 12 dígitos.
2. **Franjas de turno:** el horario de cada turno para clasificar la hora de apertura de los tickets. No pueden solaparse y deben cubrir las 24 horas. "Día Intermedio" no es franja de apertura: se asigna a cada técnico en Configuración.
3. **Prioridades y SLA:**
   - **Prioridad P1:** por defecto "Mayor".
   - **Objetivo de SLA en horas por prioridad:** si no lo tiene definido, déjelo vacío.
   - **Horas "sin actualizar" por prioridad.**

Todo se puede cambiar después en **Configuración**.

## 3. Iniciar sesión

Elija su usuario y escriba su PIN. Después de 5 intentos fallidos seguidos, el sistema pide esperar (30 s, luego 60 s, y así hasta 5 minutos). Si olvida su PIN, el coordinador le asigna uno nuevo.

| Perfil | Qué ve |
|---|---|
| Coordinador | Todo |
| Consulta con técnico asociado | Dashboard, sus propios tickets en Novedades, Estaciones, Tipificaciones, sus propias métricas en Responsables y Calidad, y los reportes del equipo |
| Consulta sin técnico (jefatura) | Dashboard, Estaciones, Tipificaciones y los reportes del equipo, sin métricas individuales |

## 4. Avisos al iniciar y campana

Debajo de la barra superior aparece una **barra de avisos** cuando hay algo pendiente:

| Aviso | Cuándo aparece |
|---|---|
| **NOT-01** | La última importación es de hace más de 1 día (se cambia en el parámetro `dias_importacion_desactualizada`). |
| **NOT-02** | Hay hallazgos nuevos de severidad ALTA. |
| **NOT-03** | El paquete mensual del mes anterior no se ha generado (solo coordinador). |
| **NOT-04** | Los lunes, si quedan tickets de la muestra semanal de calidad sin evaluar (solo coordinador). |

El botón "Ir a…" lleva a la pantalla correspondiente. La **campana** muestra cuántos hallazgos nuevos de severidad ALTA hay; al pulsarla se abre la pantalla de Hallazgos.

## 5. Exportar desde GLPI e importar

En GLPI, haga la búsqueda de tickets y expórtela a **CSV**. El analizador está preparado para las 10 columnas de su exportación.

**Importe a diario.** El CSV solo trae el estado actual de cada ticket, así que el analizador detecta los escalamientos, soluciones, cierres y reaperturas comparando una importación con la anterior.

En la pantalla **Importar**:
1. **Elegir archivo CSV…** Se detecta el formato y se usa el perfil guardado si existe. Si el archivo ya se importó, se avisa.
2. **Revise la asociación de columnas.** Los campos con * son obligatorios.
3. **Validar vista previa.** Cada fila queda:
   - **verde:** válida;
   - **amarillo:** con advertencia, pero se carga;
   - **rojo:** con error, no se carga.

   Si aparecen estados o prioridades desconocidos, asócielos y vuelva a validar.
4. **Importar filas válidas.** Antes se hace un respaldo automático. Al terminar se ejecutan solos:
   - los **hallazgos**;
   - los **snapshots** de los meses y semanas ya cerrados;
   - los avisos **NOT-02** y **NOT-05** (KPI crítico en rojo), que aparecen en el resumen.
5. **Exportar filas con error** genera un CSV con el motivo de cada una.

### Seguimientos y tareas

La pestaña **Seguimientos y tareas** importa un segundo CSV de GLPI con las notas de cada ticket (ID del ticket, fecha, autor y contenido; tipo, privado, categoría de tarea y duración son opcionales). Importe primero el CSV de tickets: las notas de tickets desconocidos se marcan en rojo. Una nota ya importada no se duplica aunque el archivo se cargue de nuevo. Las notas sirven para:
- el tiempo de primera respuesta (KPI-13);
- el % de tickets bien documentados (KPI-14);
- precalificar los criterios de calidad y mostrarlas al evaluar.

La etiqueta al inicio de una nota, por ejemplo `[DIAG]` o `[ESC-N2]`, se guarda aparte para los criterios que la piden.

## 6. Clasificación (coordinador)

La exportación no trae estación, categoría, causa ni tipo de solución. Se asignan aquí con listas desplegables:

1. **Ver:** "Pendientes de clasificar" (primero los resueltos) o "Todos los recibidos en el período".
2. **Seleccionar:** uno o varios tickets (Ctrl o Mayús + clic).
3. **Asignar:** elija los valores que quiera en Estación, Categoría (las 62 del catálogo), Causa y Tipo de solución. "(no cambiar)" deja el valor actual y "(quitar el valor)" lo borra.
4. **Aplicar a los seleccionados.**

**Sugerir estación desde Ubicación…** propone la estación del catálogo cuyo nombre coincide con el último nivel de la Ubicación de GLPI. Se asigna solo si usted confirma.

La clasificación **no se pierde al reimportar**, y cada cambio queda en el Historial. Las estaciones se crean en **Configuración > Estaciones**.

## 7. Dashboard

- **Tarjetas:** una por indicador, con valor, semáforo (✔ Verde, ▲ Amarillo, ✖ Rojo, ℹ Informativo) y variación frente al período anterior (pts = puntos porcentuales). Al pasar el mouse se ve la fórmula y las notas.
  - **≈** indica un valor aproximado.
  - **⚠ muestra pequeña** indica menos de 10 tickets.
- **Criticidad global:** el peor semáforo entre los indicadores críticos.
- **Hallazgos nuevos:** conteo por severidad y los más recientes.
- **Gráficos:**
  - recibidos frente a resueltos;
  - backlog;
  - abiertos por prioridad;
  - recibidos por estado;
  - carga por técnico;
  - brecha frente a la meta.
- **REP-01 en Excel / CSV:** acceso rápido al reporte.

### Indicadores

| Indicador | Cálculo |
|---|---|
| KPI-04 Total gestionados | (soluciones + escalamientos del período) / recibidos × 100. Un ticket escalado dos veces cuenta dos. Puede superar 100 %. |
| KPI-05 Tasa de escalamiento | escalamientos / (soluciones + escalamientos) × 100. Verde hasta 20 %, amarillo hasta 35 %. |
| KPI-06 Tiempo de resolución | Mediana de horas (P90 en la ayuda). |
| KPI-07 Cumplimiento SLA | Resueltos dentro del objetivo de su prioridad / resueltos con objetivo. |
| KPI-08 Resueltos sin cerrar | De los resueltos en el período, los que siguen sin cierre después de 2 días. Depende del visto bueno del autor. |
| KPI-09 Completitud de clasificación | Resueltos con estación, categoría, causa y tipo de solución asignados / resueltos. |
| KPI-10 Uso de «Otros» | Tickets clasificados en OTR-01 / tickets con categoría. |
| KPI-11 Reincidencia | Tickets cuyo caso (estación + título) ya había ocurrido en los 7 días anteriores. |
| KPI-12 Reaperturas | Reaperturas / resueltos. |
| KPI-16 Sin actualizar | Abiertos sin movimiento por más horas que el umbral de su prioridad. |
| KPI-17 Tiempo en escalado | Mediana de horas que un ticket pasa escalado. |

Los tiempos no descuentan la espera, porque la exportación no la trae.

## 8. Novedades

Es la lista de tickets abiertos y de los recibidos en el período. Tiene accesos rápidos:
- sin actualizar más del plazo;
- resueltos sin cerrar;
- P1 abiertos;
- escalados antiguos.

**Doble clic** en un ticket abre su detalle: datos y pestañas de eventos, cambios detectados, seguimientos y calidad (la evaluación vigente). El coordinador tiene además el botón **Evaluar calidad**.

## 9. Hallazgos (coordinador)

Son alertas automáticas. Se generan después de cada importación, al iniciar y con **Detectar ahora**.

| Regla | Qué detecta |
|---|---|
| HAL-01 Caso repetido | El mismo título (sin números ni tildes) en la misma estación: 3 o más veces en una semana, o 5 o más en un mes. |
| HAL-02 Pico por estación | Semana muy por encima de la media de las 8 anteriores. |
| HAL-03 Categoría en crecimiento | Mes con 1,5 veces el promedio de los 3 anteriores. |
| HAL-04 Sin seguimiento | Abierto sin actualización por más del plazo de su prioridad. |
| HAL-05 Resuelto sin cerrar | Por técnico. |
| HAL-06 Escalado estancado | Más de 5 días escalado (ALTA si pasa de 10). |
| HAL-07 P1 abierto | Cualquier P1 abierto. |
| HAL-08 Sobrecarga | Técnico con muchos más abiertos que el equipo. |
| HAL-09 Tickets sin clasificar | Resueltos a los que les falta clasificación. |
| HAL-10 Semáforo en rojo | KPI crítico en rojo. |
| HAL-11 Reapertura | Ticket reabierto. |
| HAL-12 Importación desactualizada | La última importación es demasiado antigua. |

**Marcar revisado…** y **Descartar…** piden un comentario, obligatorio al descartar, y quedan en el Historial. Un hallazgo descartado no vuelve a aparecer como nuevo. Los de situación actual (P1 abierto, sin seguimiento…) se **cierran solos** cuando la situación termina. **Ver tickets relacionados** muestra los tickets del hallazgo; con doble clic se abre cada uno.

## 10. Estaciones y Tipificaciones

Usan la estación y la categoría asignadas en Clasificación.

- **Estaciones:**
  - ranking por volumen, reincidencia, tiempo de resolución y abiertos;
  - al hacer clic en una estación: su tendencia semanal, sus familias más frecuentes y sus casos repetidos;
  - pestaña con el **mapa de calor** estación × familia.
- **Tipificaciones:**
  - distribución por familia;
  - tendencia mensual por familia;
  - categorías del período;
  - variación frente al promedio de 3 meses;
  - uso de OTR-01 y tickets sin categoría.

## 11. Responsables

Muestra las métricas de cada técnico en el período, incluido el **% documentación** (KPI-14). **La cantidad de tickets es informativa (carga), no una calificación.** El usuario de consulta solo ve su propia fila. **REP-03** genera el reporte.

## 12. Calidad

La calidad se mide para mejorar y conversar, no para castigar. Ninguna métrica se usa sola, los tiempos se comparan dentro de la misma categoría y cada técnico se compara primero consigo mismo.

**Evaluar tickets (coordinador).**
1. Elija la **semana**: se propone una **muestra** con todos los P1, los escalados largos, al menos un ticket por técnico cada 2 semanas y otros al azar, hasta el parámetro `tickets_auditoria_semana`. Use **Agregar a la muestra** y **Quitar de la muestra** para ajustarla.
2. Elija un ticket y pulse **Evaluar**, o escriba su número.
3. Confirme el **tipo de caso**. Los criterios generales se muestran siempre, y los específicos según el tipo; por ejemplo, un escalamiento suma 6 criterios propios. Los marcados **CRÍTICO** pesan más.
4. Cada casilla alterna entre **✔ cumple**, **✖ no cumple** y **— no aplica**. Los marcados **AUTO** ya vienen precalificados con los datos y las notas del ticket. Si cambia uno, debe escribir una nota.
5. El **puntaje** se actualiza al marcar. Escriba la **retroalimentación** y pulse **Guardar evaluación**.

El resultado es **Conforme**, **Por mejorar** o **No conforme** según los umbrales `umbral_conforme` y `umbral_por_mejorar`. Un crítico fallido da No conforme. Reevaluar crea una versión nueva y la anterior queda en el Historial.

**Histórico por técnico.** Semana a semana: atendidos, abiertos, tiempos, SLA y % documentación, con flechas ↑ ↓ → frente a la semana anterior y al promedio de 4 semanas.

**Rendimiento.** Por técnico:
- tiempos de primera respuesta, solución y cierre;
- el **índice de velocidad**: menos de 1 es más rápido que el equipo en casos de la misma categoría;
- % de cierre formal, reaperturas y escalamientos por familia.

**Comparativo y ranking (solo coordinador).**
- El índice combina calidad, velocidad y completitud con los pesos de Configuración.
- Excluye a quien no alcanza la muestra mínima o está marcado "no incluir en ranking".
- El **radar** compara al técnico elegido con el promedio del equipo.
- Es de uso interno: no lo publique.

**Incumplimiento por criterio.** Porcentaje de "no cumple" por criterio. Los que llegan al 30 % se marcan como tema de capacitación.

El usuario de consulta ve solo su propio histórico, rendimiento e incumplimiento, nunca el ranking.

## 13. Reportes

Elija el reporte, el formato (**PDF**, **Excel** o **CSV**) y pulse **Generar reporte**. Se usan el período y los filtros de la barra superior. El archivo queda en `exportaciones\AAAA-MM\`, y **Abrir archivo** lo abre.

| Reporte | Contenido |
|---|---|
| REP-01 | Resumen de indicadores |
| REP-02 | Estaciones |
| REP-03 | Responsables |
| REP-04 | Tipificaciones |
| REP-05 | Hallazgos |
| REP-06 | Calidad de soporte – histórico (coordinador): una hoja por técnico, semana a semana |
| REP-07 | Calidad de soporte – comparativo (coordinador): ranking, radar, tendencia de 3 meses e incumplimiento por criterio. Uso interno |
| REP-08 | Distribución de horas SEGMOV (coordinador): escriba el **total de horas del mes**. Se reparten entre las estaciones marcadas "Incluir en SEGMOV" según sus casos, y la suma da siempre el total exacto. Generarlo guarda la distribución del mes. |
| REP-09 | SLA: cumplimiento por prioridad, cliente, familia y técnico; tickets fuera de SLA o en riesgo; tendencia de 6 meses |
| REP-11 | Datos para auditoría (coordinador), con la evaluación de calidad vigente de cada ticket |

**Anonimizar autores y técnicos** reemplaza los nombres por "Persona 001", "Persona 002"… Úsela al compartir fuera del equipo. En el PDF, los textos muy largos se recortan; el Excel los trae completos.

### Paquete mensual (coordinador)

**Generar paquete mensual…** pide el resumen ejecutivo y el plan de mejora, y crea:
- un **PDF** y un **Excel** con: resumen ejecutivo, indicadores, SLA, tendencias de 6 meses, los 5 casos más repetidos, hallazgos, calidad del área (KPI-14, KPI-15, resultados de las evaluaciones y criterios con más incumplimiento, sin datos por técnico), SEGMOV (si ya generó REP-08 para ese mes) y plan de mejora;
- un **borrador de correo** (`.eml`) con el PDF adjunto, que se abre en Outlook para revisar y enviar. El destinatario es el parámetro `correo_jefatura`. El aplicativo no envía nada por su cuenta.

Tras generarlo, el aviso NOT-03 desaparece. **Borrador de correo: hallazgos ALTA** prepara un correo con los hallazgos nuevos de severidad alta.

**Resúmenes semanales por técnico** crea un borrador `.eml` por cada técnico con actividad en la última semana completa. Cada uno trae **solo sus propias** métricas, su comparación consigo mismo y la retroalimentación de sus evaluaciones, nunca el ranking ni datos de otros. El destinatario va vacío: complételo en Outlook antes de enviar.

## 14. KPIs (coordinador)

- **KPIs predefinidos:** se cambian sus umbrales verde y amarillo, la meta, la visibilidad en el dashboard y la marca de crítico. No se pueden eliminar.
- **Nuevo KPI:**
  1. Escriba el nombre y elija el tipo: conteo, porcentaje, o mediana, promedio o P90 de tiempo.
  2. Agregue condiciones con **Agregar condición…**, por ejemplo "Familia de categoría: REC" y "Tiene causa: No". No se escribe código.
  3. En un porcentaje, las condiciones del denominador definen la base.
  4. **Vista previa** muestra el valor en el período actual sin guardar; **Guardar** lo agrega al dashboard.
- **Tendencia de 12 meses:** aparece al elegir un KPI, tomada de los snapshots. **Generar snapshot del período** guarda los valores del mes o la semana elegidos.

## 15. Tablas y exportación

Todas las tablas permiten ordenar, buscar en todas las columnas o en una, y exportar a Excel o CSV lo que se ve. La casilla **"Anonimizar personas al exportar"** reemplaza los nombres de personas.

## 16. Configuración (coordinador)

| Pestaña | Para qué |
|---|---|
| Parámetros | Umbrales y valores editables, incluidos los de hallazgos, el porcentaje "en riesgo" del SLA y `correo_jefatura` |
| Turnos | Franjas de apertura. Al guardar se actualiza `config.ini` y se recalcula el turno de los tickets. |
| Técnicos | Nombre a mostrar, turno, activo e incluir en ranking |
| Estaciones | Catálogo de estaciones: nombre, cliente, incluir en SEGMOV y activa |
| Festivos | Agregar, eliminar o proponer los festivos de ley de Colombia del año |
| Usuarios | Crear usuarios, activarlos o desactivarlos y restablecer su PIN |
| Respaldos | Crear un respaldo manual o restaurar uno (antes se respalda la base actual) |
| Perfiles de importación | Ver y eliminar perfiles |

## 17. Historial

Es la auditoría de los cambios manuales:
- parámetros, KPIs, técnicos y estaciones;
- clasificación de tickets y hallazgos revisados;
- usuarios, festivos, turnos y perfiles;
- importaciones, snapshots, SEGMOV y restauraciones.

La base de datos impide modificar o borrar estos registros.

## 18. Respaldos y problemas

- **Respaldos automáticos:** antes de cada importación y uno diario. Se conservan 30 días.
- **Mensajes de error:** aparecen en español. El detalle queda en `logs\app.log`.
- **Si `config.ini` tiene un error**, el aplicativo indica qué corregir. Si lo borra, se vuelve a crear.
