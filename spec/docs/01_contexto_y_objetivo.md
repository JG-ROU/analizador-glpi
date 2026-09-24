# 01 – Contexto y objetivo

## Contexto
- **El área:** coordinación de Soporte de Aplicaciones, con 9 técnicos en 4 turnos (Mañana, Día Intermedio, Tarde, Nocturno). Atiende una operación 24/7 de sistemas de recaudo de peajes para varios clientes (concesiones) y sus estaciones.
- **La herramienta de tickets:** GLPI 9.1.4. Recibe alrededor de 200 tickets al mes.
- **Estándares que el aplicativo debe aprovechar:**
  - **Tipificación:** categorías con código prefijo, p. ej. `APL-01 Bloqueo o no responde`; 12 familias, 62 hojas (`catalogos/tipificacion.csv`).
  - **Causa:** primera línea de la solución `CAUSA: CAU-xx | detalle` (`catalogos/causas.csv`).
  - **Seguimientos:** notas con etiquetas `[APERTURA]`, `[DIAG]`, `[ESC]`, `[SEG-ESC]`, `[TURNO]`… (`catalogos/etiquetas_seguimiento.md`).
  - **Auditoría de calidad:** 34 criterios por tipo de caso (`catalogos/criterios_calidad.csv`).
- **Hoy los reportes se arman a mano en Excel.** Hay tickets resueltos que no se cierran formalmente, y eso distorsiona los indicadores.

## Objetivo
1. Convertir las exportaciones de GLPI en indicadores confiables, sin trabajo manual.
2. Detectar automáticamente problemas: reincidencias, casos sin seguimiento, resueltos sin cerrar, picos por estación.
3. Medir el desempeño de cada técnico **de forma justa**: con contexto, varias métricas y calidad de documentación, nunca solo por número de tickets.
4. Generar reportes y un paquete mensual (SLA, indicadores, distribución de horas SEGMOV) listos para enviar.

## Usuarios
| Perfil | Acceso |
|---|---|
| Coordinador | Todo: importar, configurar KPIs y parámetros, evaluar calidad, ver ranking, generar reportes. |
| Consulta (técnico o jefatura) | Dashboard, estaciones, tipificaciones y sus propias métricas. Sin ranking de otros técnicos ni evaluaciones ajenas. |

## Alcance
- Importación de CSV de tickets (obligatorio) y de seguimientos y tareas (opcional).
- Dashboard con KPIs predefinidos y **KPIs creados por el usuario**.
- Módulos: Novedades, Estaciones, Responsables, Tipificaciones, Hallazgos, Calidad de soporte y Reportes.
- SLA, reporte mensual, distribución SEGMOV y notificaciones (alertas y borradores de correo).
- Ejecutable portable con base de datos interna.

## Fuera de alcance (por ahora)
- Conexión directa a la API REST de GLPI: se deja una interfaz preparada (`core/fuentes/`) para agregarla después sin cambiar el resto.
- Escribir en GLPI: el analizador es de solo lectura.
- Envío automático de correos con credenciales.
