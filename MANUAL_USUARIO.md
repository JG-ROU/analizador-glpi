# Manual de usuario – Analizador GLPI (Fase 1)

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
| `exportaciones\` | Reportes y tablas exportadas, por mes |

El aplicativo funciona sin internet. Los datos quedan solo en este equipo.

## 2. Primera ejecución: asistente de configuración

El asistente pide:

1. **Coordinador:** su nombre y un PIN de 4 a 12 dígitos. El coordinador administra todo y crea a los demás usuarios.
2. **Franjas de turno:** el horario de cada turno para clasificar la hora de apertura de los tickets. No pueden solaparse y deben cubrir las 24 horas. Por defecto: Mañana 06:00–14:00, Tarde 14:00–22:00 y Nocturno 22:00–06:00. "Día Intermedio" no es franja de apertura: se asigna a cada técnico en Configuración.
3. **Prioridades y SLA:**
   - **Prioridad P1:** por defecto "Mayor".
   - **Objetivo de SLA en horas por prioridad:** si todavía no lo tiene definido, déjelo vacío. El indicador de SLA avisará que falta.
   - **Horas "sin actualizar" por prioridad:** a partir de cuántas horas sin movimiento un ticket abierto se considera desatendido.

Todo se puede cambiar después en **Configuración**.

## 3. Iniciar sesión

Elija su usuario y escriba su PIN. Después de 5 intentos fallidos seguidos, el sistema pide esperar antes de volver a intentar (30 s, luego 60 s, y así hasta 5 minutos). No bloquea la cuenta. Si olvida su PIN, el coordinador puede asignarle uno nuevo.

| Perfil | Qué ve |
|---|---|
| Coordinador | Todo: importar, configurar, métricas de todos los técnicos y reportes |
| Consulta con técnico asociado | Dashboard del equipo, sus propios tickets en Novedades y sus propias métricas en Responsables |
| Consulta sin técnico (jefatura) | Solo el Dashboard del equipo |

## 4. Exportar desde GLPI

En GLPI, haga la búsqueda de tickets y expórtela a **CSV**. El analizador está preparado para las 10 columnas que trae su exportación: ID, Título, Entidad, Estado, Autor, Asignado a – Técnico, Fecha de Apertura, Última actualización, Prioridad y Ubicación.

**Importe a diario.** El CSV solo trae el estado actual de cada ticket, así que el analizador detecta los escalamientos, soluciones, cierres y reaperturas comparando una importación con la anterior. Si pasan varios días entre importaciones, se pierden los cambios intermedios; por ejemplo, un ticket que se escaló y volvió en ese lapso. Cuando la última importación tiene más de un día, la fecha aparece en **rojo** en la barra superior. El número de días se cambia en Configuración (`dias_importacion_desactualizada`).

## 5. Importar

1. **Elegir archivo CSV…** El sistema detecta la codificación, el separador, las columnas y el formato de fecha.
   - Si ya hay un perfil guardado para esas columnas, lo usa.
   - Si el archivo ya se importó antes, lo avisa y no lo vuelve a cargar.
   - Si las fechas admiten día/mes y mes/día, le pide confirmar el formato.
2. **Revise la asociación de columnas.** Los campos con * son obligatorios.
3. **Validar vista previa.** Cada fila queda:
   - **verde:** válida;
   - **amarillo:** con advertencia, pero se carga (por ejemplo, un ticket sin técnico asignado);
   - **rojo:** con error, no se carga. El motivo aparece en la columna "Motivos": fecha inválida, ID vacío, estado desconocido, etc.
4. **Estados o prioridades nuevos:** si el archivo trae un valor que el perfil no conoce, por ejemplo un estado nuevo en GLPI, aparece en el recuadro "Estados y prioridades que el perfil no conoce". Asócielo al estado o nivel equivalente y vuelva a validar. La asociación queda guardada en el perfil.
5. **Importar filas válidas.** Antes de cargar se hace un respaldo automático. Al final verá un resumen con los tickets nuevos, los actualizados, los que no cambiaron, las filas con error y los eventos detectados.
6. **Exportar filas con error** genera un CSV con los valores originales y el motivo, para corregirlos.

En la parte inferior está el **historial de importaciones**.

## 6. Barra superior

- **Período:** semana, mes o rango de fechas. Los indicadores se calculan para ese período y se comparan con el anterior.
- **Turno:** filtra por el turno en que se abrió el ticket.
- **Última importación:** en rojo si está desactualizada.
- **Campana de alertas:** se habilita en la Fase 2.

## 7. Dashboard

- **Tarjetas de indicadores:** cada una muestra el valor, el semáforo con ícono y texto (✔ Verde, ▲ Amarillo, ✖ Rojo, ℹ Informativo) y la variación frente al período anterior. Al pasar el mouse sobre una tarjeta se ve su fórmula, la base de cálculo, la meta y las notas.
  - **≈** indica un valor aproximado: la fecha de solución se toma de la importación en que el ticket apareció resuelto.
  - **⚠ muestra pequeña** indica que el cálculo se hizo con menos de 10 tickets (se cambia en Configuración).
- **Criticidad global:** el peor semáforo entre los indicadores críticos, que por defecto son Total gestionados, Tasa de escalamiento, SLA y Resueltos sin cerrar.
- **Gráficos:**
  - recibidos frente a resueltos por semana;
  - backlog;
  - abiertos por prioridad;
  - recibidos por estado;
  - carga por técnico;
  - brecha frente a la meta.
- **REP-01 en Excel / CSV:** genera el Resumen de indicadores en `exportaciones\AAAA-MM\`.

### Cómo se calculan los indicadores principales

| Indicador | Cálculo |
|---|---|
| Total gestionados (KPI-04) | (soluciones + escalamientos del período) / tickets recibidos en el período × 100. Se cuentan **eventos**: un ticket escalado dos veces cuenta dos. Puede superar 100 %. |
| Tasa de escalamiento (KPI-05) | escalamientos / (soluciones + escalamientos) × 100. Verde hasta 20 %, amarillo hasta 35 %, rojo por encima. |
| Tiempo de resolución (KPI-06) | Mediana de horas entre la apertura y la solución (el P90 aparece en la ayuda). Se usa la mediana porque unos pocos casos muy largos distorsionan el promedio. |
| Cumplimiento SLA (KPI-07) | Resueltos dentro del objetivo de su prioridad / resueltos con objetivo definido. |
| Resueltos sin cerrar (KPI-08) | De los resueltos en el período, los que siguen sin cierre después de 2 días. Depende del visto bueno del autor: es informativo. |
| Sin actualizar (KPI-16) | Abiertos sin movimiento por más horas que el umbral de su prioridad. |

Los tiempos no descuentan la espera, porque la exportación no la trae.

## 8. Novedades

Es la lista de tickets abiertos y de los recibidos en el período. Tiene accesos rápidos:
- sin actualizar más del plazo;
- resueltos sin cerrar;
- P1 abiertos;
- escalados antiguos (5 días por defecto).

Puede filtrar por estado, prioridad y técnico. **Doble clic** en un ticket abre su detalle: datos, línea de tiempo de eventos y cambios detectados entre importaciones.

## 9. Responsables

Muestra las métricas de cada técnico en el período: carga actual, atendidos, soluciones, escalamientos, tiempos, SLA, resueltos sin cerrar, reaperturas y tickets sin actualizar. Al hacer clic en un técnico se ve su gráfico de atendidos por semana.

- **La cantidad de tickets es informativa (carga), no una calificación.**
- El usuario de consulta solo ve su propia fila.
- **REP-03 en Excel / CSV** genera el reporte de responsables.

## 10. Tablas y exportación

Todas las tablas permiten:
- ordenar haciendo clic en el encabezado;
- buscar en todas las columnas o en una;
- exportar a Excel o CSV lo que se ve en pantalla.

La casilla **"Anonimizar personas al exportar"** reemplaza los nombres de autores y técnicos por "Persona 001", "Persona 002"… Úsela cuando el archivo vaya a compartirse fuera del equipo.

## 11. Configuración (coordinador)

| Pestaña | Para qué |
|---|---|
| Parámetros | Umbrales y valores editables: muestra mínima, prioridad P1, días para alertas, objetivos de SLA, horas sin actualizar y umbrales del tiempo de resolución. Pase el mouse por la descripción para verla completa. |
| KPIs | Umbrales verde y amarillo, meta, visibilidad en el dashboard, orden y marca de crítico |
| Turnos | Franjas de apertura. Al guardar se actualiza `config.ini` y se recalcula el turno de los tickets existentes. |
| Técnicos | Se crean solos al importar. Complete el nombre a mostrar y el turno; desmarque "Activo" o "Incluir en ranking" cuando corresponda. |
| Festivos | Agregar o eliminar festivos. "Proponer festivos de Colombia" calcula los de ley del año; revíselos antes de confirmar. |
| Usuarios | Crear usuarios, activarlos o desactivarlos y restablecer su PIN |
| Respaldos | Crear un respaldo manual o restaurar uno. Antes de restaurar, se respalda la base actual. |
| Perfiles de importación | Ver y eliminar perfiles. Uno que ya se usó en importaciones no se puede eliminar. |

**Cambiar la prioridad P1** recalcula qué tickets son P1 y su tipo de caso.

## 12. Historial

Es la auditoría de los cambios manuales: parámetros, KPIs, técnicos, usuarios, festivos, turnos, perfiles, importaciones y restauraciones. Muestra quién hizo cada cambio, cuándo, y el valor antes y después. La base de datos impide modificar o borrar estos registros.

## 13. Respaldos y problemas

- **Respaldos automáticos:** antes de cada importación y uno diario. Se conservan 30 días (`retencion_respaldos` en `config.ini`).
- **Mensajes de error:** aparecen en español. El detalle técnico queda en `logs\app.log`; envíelo a soporte si el problema persiste.
- **Si `config.ini` tiene un error**, el aplicativo lo indica al abrir y dice qué valor corregir. Si lo borra, se vuelve a crear con los valores por defecto.
