# 07 – Calidad de soporte

**Principios** (obligatorios; afectan el diseño):
- Se mide para mejorar y para conversar, no para castigar. El ranking es visible **solo para el coordinador**.
- Nunca se evalúa con una sola métrica. El número de tickets es **informativo** (carga), no una calificación.
- Los tiempos se comparan **dentro de la misma categoría**. Un técnico que atiende casos difíciles no debe salir peor por eso.
- Cada técnico se compara primero consigo mismo (tendencia); después, con el equipo.
- Muestra mínima (RN-04): menos de 10 tickets en el período → no entra en el ranking.

## CAL-01 – Evaluación de documentación con checkboxes
Pantalla PAN-10, pestaña 1:
1. **Seleccionar ticket.** Se elige de una lista de pendientes por evaluar: la muestra sugerida por CAL-04 o una búsqueda.
2. **Tipo de caso.** El sistema propone el tipo inferido (IMP-04). El coordinador puede cambiarlo: Gestión, Escalamiento, Solicitud, Crítico P1, En espera externa, Cambio/despliegue o Actividad programada.
3. **Criterios.** Se muestran **solo los criterios que aplican**: los 12 generales ("Todos") más los del tipo de caso (`catalogos/criterios_calidad.csv`). Cada criterio muestra:
   - un **checkbox tri-estado**: ✔ cumple / ✖ no cumple / — no aplica;
   - una marca roja "CRÍTICO" si aplica;
   - un ícono "AUTO" si el sistema lo precalificó (CAL-02);
   - la descripción y "cómo verificar" como ayuda al pasar el mouse.
4. **Seguimientos del ticket.** Se ven al lado, con sus etiquetas resaltadas, para evaluar sin salir de la pantalla.
5. **Puntaje en vivo (CAL-03).** Se recalcula al marcar cada casilla.
6. **Guardar.** Hay un campo de retroalimentación para el técnico. Guardar deja registro en el historial.

## CAL-02 – Precalificación automática
Si hay CSV de seguimientos, el sistema precalifica los criterios "Auto" y "Semi" con las reglas de la columna `regla_script` del catálogo:

| Criterio | Regla automática |
|---|---|
| G-02 | Categoría hoja + ubicación presentes |
| G-05 | Intervalo máximo entre notas ≤ umbral según prioridad o tipo (P1 60 min; alta 4 h; media/baja 24 h), excluyendo el tiempo En espera externa |
| G-06 | Todas las tareas con categoría y duración > 0 |
| G-07 | Tipo de solución + regex CAUSA |
| G-10 | Estado Cerrado |
| G-11 | Regex de alerta `contraseña\|password\|clave:\|pwd`. **Nunca** se marca cumple automáticamente: si hay coincidencia, queda "no cumple – revisar" |
| E-02 | Documento adjunto al escalar (si el CSV trae adjuntos) |
| E-03 | Grupo de escalamiento asignado |
| E-05 | Intervalo máximo entre [ESC] y [SEG-ESC] ≤ umbral |
| P-02 | Intervalo máximo entre notas de P1 ≤ 60 min hasta [P1-RESTABLECIDO] |
| C-02 | Hora de [CAMBIO-EJEC] dentro de la ventana lun–jue antes de 16:00 y no festivo |
| W-02 | Recordatorios ≤ 26 h |
| Semi (resto) | La etiqueta existe y los campos de la plantilla (`Motivo:`, `Sigue:` con hh:mm, `Verificación:`…) no están vacíos |

- **Correcciones:** el coordinador puede cambiar un resultado automático. Queda como AUTO_CORREGIDO con nota obligatoria.
- **Sin seguimientos importados:** todos los criterios son manuales.

## CAL-03 – Puntaje
- **% cumplimiento** = criterios ✔ / (✔ + ✖). Los "no aplica" no cuentan.
- **Críticos fallidos** = criterios CRÍTICO marcados ✖.
- **Resultado:**
  - **Conforme:** % ≥ `umbral_conforme` (90 %) y 0 críticos fallidos.
  - **Por mejorar:** % ≥ `umbral_por_mejorar` (70 %) y 0 críticos fallidos.
  - **No conforme:** en cualquier otro caso.
- *Caso de prueba:* 17 criterios evaluados, 14 ✔, 3 ✖ (ninguno crítico) → 82 % → Por mejorar. El mismo caso con uno de los ✖ crítico → No conforme.

## CAL-04 – Muestra sugerida para evaluar
Cada semana el sistema propone `tickets_auditoria_semana` (10) tickets cerrados la semana anterior:
- todos los P1;
- todos los escalados con más de 5 días abiertos;
- al menos 1 por técnico cada 2 semanas;
- el resto al azar.

El coordinador puede agregar o quitar tickets.

## CAL-05 – Histórico por técnico semana a semana
- **Series por técnico (semana ISO):** atendidos (tickets donde fue técnico principal y se resolvieron en la semana), abiertos al corte, mediana de resolución, % SLA, % documentación.
- **Gráfico de líneas** con flechas ▲/▼ y % de variación frente a la semana anterior y al promedio de 4 semanas.
- **Contexto:** se muestra el turno del técnico, porque la carga varía por turno.

## CAL-06 – Rendimiento
Por técnico y período:
- mediana de horas hasta la primera respuesta, la solución y el cierre;
- **Índice de velocidad normalizado** = mediana de las razones (horas_resolucion del ticket / mediana del equipo en la misma categoría) de sus tickets. Menos de 1 = más rápido que el equipo en casos equivalentes;
- % cierre formal, % reaperturas, % escalados (comparado solo por familia).

## CAL-07 – Panel comparativo y ranking (solo coordinador)
- **Tres dimensiones** en escala 0–100:
  - **Velocidad** = 100 × clamp(2 − índice normalizado, 0, 1);
  - **Calidad** = promedio del % de evaluación (CAL-03) menos 10 puntos por cada crítico fallido del período, con mínimo 0;
  - **Completitud** = KPI-09 del técnico.
- **Índice del técnico** = pesos configurables (propuesta: calidad 50 %, velocidad 30 %, completitud 20 %).
- **Visualización:**
  - tabla ordenable;
  - gráfico de radar por técnico;
  - comparación con el promedio del equipo;
  - tendencia de 3 meses.
- **Filtros de inclusión:** se excluye a quien no cumple la muestra mínima o tiene `incluir_en_ranking = 0` (p. ej. vacaciones).
- **Aviso fijo en pantalla:** "Uso interno para conversaciones de desempeño; no publicar."

## CAL-08 – Incumplimiento por criterio
- **Cálculo:** % de ✖ por criterio en el período, para el equipo y por técnico.
- **Alerta:** los criterios con 30 % o más se destacan como tema de capacitación.
