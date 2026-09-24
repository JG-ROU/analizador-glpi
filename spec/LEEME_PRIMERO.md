# LÉEME PRIMERO – Instrucciones para la IA desarrolladora

Vas a desarrollar **Analizador GLPI**, un aplicativo de escritorio portable para Windows (.exe) hecho en **Python + PySide6** con base de datos interna **SQLite**.

**Qué hace:**
1. Importa exportaciones CSV de GLPI 9.1.4.
2. Calcula indicadores (KPIs) configurables, SLA y hallazgos automáticos.
3. Evalúa la calidad de la documentación de los técnicos.
4. Genera dashboards, reportes (Excel, CSV, PDF) y notificaciones mensuales.

**Para qué:** mejorar la gestión de un equipo de soporte de aplicaciones 24/7 de sistemas de recaudo de peajes.

**Cómo se trazan los requisitos:** todo requisito tiene un ID: IMP (importación), KPI (indicadores), RN (reglas), PAN (pantallas), CAL (calidad), HAL (hallazgos), REP (reportes), NOT (notificaciones), RNF (no funcionales) y CA (criterios de aceptación). Úsalos para reportar tu avance.

## 1. Orden de lectura (obligatorio antes de escribir código)
| # | Archivo | Contenido |
|---|---|---|
| 1 | `spec/docs/01_contexto_y_objetivo.md` | Problema, usuarios, alcance |
| 2 | `spec/docs/02_glosario.md` | Términos del dominio (úsalos en código e interfaz) |
| 3 | `spec/docs/03_fuente_de_datos_e_importacion.md` | CSV de GLPI, mapeo de columnas, validación, campos derivados |
| 4 | `spec/docs/04_modelo_de_datos.md` | Tablas SQLite |
| 5 | `spec/docs/05_kpis_y_reglas_de_calculo.md` | Fórmulas, KPIs configurables, semáforos |
| 6 | `spec/docs/06_modulos_y_pantallas.md` | Pantallas PySide6 |
| 7 | `spec/docs/07_calidad_de_soporte.md` | Evaluación con checkboxes, métricas por técnico, ranking justo |
| 8 | `spec/docs/08_hallazgos_automaticos.md` | Reglas de alertas y reincidencia |
| 9 | `spec/docs/09_reportes_sla_y_notificaciones.md` | Reportes, SLA, SEGMOV, mensual, correos |
| 10 | `spec/docs/10_requisitos_no_funcionales.md` | Portabilidad, rendimiento, seguridad |
| 11 | `spec/docs/11_arquitectura_y_estructura.md` | Stack y estructura de carpetas |
| 12 | `spec/docs/12_fases_y_criterios_de_aceptacion.md` | Fases, entregables y pruebas |
| — | `spec/catalogos/` | Catálogos reales: tipificación (62 categorías), causas, tipos de solución, 34 criterios de calidad, etiquetas de seguimiento |

## 2. Cómo debes trabajar
1. **Primera respuesta, sin código:**
   - resumen de lo que entendiste (máximo 15 líneas);
   - preguntas abiertas (solo las que bloquean; en lo demás, propón una opción);
   - arquitectura y modelo de datos final (confirma o ajusta `04` justificando);
   - plan de la Fase 1 en tareas pequeñas.

   Después, **espera mi aprobación**.
2. Trabaja **una fase a la vez** (`12`). No adelantes funcionalidades de fases posteriores.
3. **Por cada tarea:**
   - implementa;
   - escribe pruebas (pytest) de las reglas y fórmulas que toca;
   - ejecútalas y reporta el resultado.
4. **Código completo:** entrega el código completo de cada archivo nuevo o modificado. Nunca uses "…resto igual…".
5. **Cambios de esquema:** cualquier cambio en la base de datos va con migración. Los datos existentes no se pierden.
6. **Conflictos y ambigüedades:** si algo es ambiguo o técnicamente riesgoso, dilo y propón una alternativa. No lo resuelvas en silencio.
7. **Datos:** no inventes datos del negocio. Para pruebas usa el generador de CSV ficticio (`data/muestras/`).
8. **Al cerrar cada fase entrega:**
   - requisitos cubiertos (IDs);
   - resultado de las pruebas;
   - criterios CA verificados y cómo se verificaron;
   - instrucciones para generar el .exe;
   - pendientes y riesgos.

## 3. Convenciones
- **Idioma:** interfaz, mensajes y documentación en **español**. Identificadores del dominio en español sin tildes (`ticket`, `tecnico`, `estacion`, `hallazgo`). Comentarios en español.
- **Configuración:** en `config.ini` para parámetros de arranque y en la tabla `parametro` para lo que el usuario edita en pantalla. Nada de valores fijos en el código.
- **Fechas:** en hora local de Colombia (America/Bogota, UTC-5, sin horario de verano).
- **Separación de capas:** toda la lógica de cálculo vive en `core/` y se prueba sin interfaz. `ui/` solo muestra y captura.

## 4. Definición de "terminado"
- Funciona desde el .exe empaquetado.
- Tiene pruebas de sus reglas y todas pasan.
- Los errores se muestran en español al usuario y el detalle queda en `logs/app.log`.
- Los cambios manuales del usuario (evaluaciones, parámetros, catálogos) quedan en el historial.
