# Etiquetas y plantillas de seguimiento (estándar RB-COORD-DOC)

Cada nota empieza con una etiqueta entre corchetes. El analizador las detecta con la expresión regular `^\[([A-Z0-9-]+)\]`. La solución empieza con `CAUSA: CAU-xx | detalle`.

## [APERTURA]
```
[APERTURA] hh:mm
Reporta:     <nombre / cargo / teléfono> por <canal: llamada, WhatsApp, Teams, correo, monitoreo>
Estación:    <estación> | Carril: <n.º o N/A>
Aplicación:  <aplicación>
Síntoma:     <qué ve el usuario; mensaje de error textual>
Desde:       <hh:mm> | Impacto: <carriles/usuarios afectados; ¿hay recaudo? sí/no>
Prioridad:   <nivel> porque <razón>
```

## [DIAG]
```
[DIAG] hh:mm
Hice:      1) <prueba>  2) <prueba>  3) <prueba>
Encontré:  <resultado de cada prueba; error textual; log adjunto>
Estado:    Hipótesis: <causa probable>
Sigue:     <siguiente acción> – <yo> – antes de <hh:mm>
```

## [AVANCE]
```
[AVANCE] hh:mm
Hice:      <acción>
Encontré:  <resultado>
Estado:    <sigue la falla / mejoró / resuelto parcialmente>
Sigue:     <próximo paso> – <quién> – antes de <hh:mm>
```

## [ESC]
```
[ESC] hh:mm
Escalado a:  <área> | Contacto: <persona> | Medio: <GLPI/correo/Teams> | Ref.: <n.º ticket o asunto>
Motivo:      <por qué no se resuelve en soporte; runbook consultado>
Pruebas:     <qué se probó y resultado>
Evidencias:  <adjuntos: capturas, logs, horas, transacciones>
Impacto:     <carriles/usuarios; ¿hay recaudo?>
Se solicita: <acción concreta que se espera del área>
Sigue:       seguimiento al área – <yo> – <fecha hh:mm>
```

## [SEG-ESC]
```
[SEG-ESC] fecha hh:mm
Consulté a: <área/persona> por <medio>
Respuesta:  <avance / sin respuesta>
Sigue:      <próximo seguimiento> – <yo> – <fecha hh:mm>
```

## [RETORNO]
```
[RETORNO] hh:mm
El área <área> respondió: <qué hizo / versión / corrección>
Apliqué:    <acción en la estación>
Verificación: <cómo se confirmó>
Estado:     listo para solución y cierre
```

## [REQ]
```
[REQ] hh:mm
Solicita:    <qué>
Para:        <usuario/estación/aplicación>
Aprobación:  <quién autoriza y cómo; 'no aplica' si no se requiere>
Datos:       <completos / falta: …>
Sigue:       ejecutar – <yo> – antes de <fecha hh:mm>
```

## [EJEC]
```
[EJEC] hh:mm
Hice:       <acción ejecutada>
Evidencia:  <captura / confirmación del usuario>
Nota: las credenciales se entregan por canal seguro; nunca se escriben en el ticket.
```

## [P1-INICIO]
```
[P1-INICIO] hh:mm
Detección:  <hh:mm> por <quién/monitoreo>
Afectación: <estaciones/carriles/aplicación>; ¿recaudo detenido? <sí/no>
Aviso:      coordinador <hh:mm> | equipo Teams <hh:mm> | cliente <hh:mm o N/A>
Acciones inmediatas: <…>
Próxima actualización: <hh:mm (máx. 60 min)>
```

## [P1-ACT]
```
[P1-ACT] hh:mm
Estado:     <sin cambios / parcialmente restablecido / …>
Acciones desde la última actualización: <…>
Próxima actualización: <hh:mm>
```

## [P1-RESTABLECIDO]
```
[P1-RESTABLECIDO] hh:mm
Servicio restablecido a las <hh:mm>; verificado con <quién/cómo>
Causa preliminar: <…>
```

## [P1-CIERRE]
```
[P1-CIERRE]
Duración:   <detección → restablecimiento>
Impacto:    <carriles, estaciones, tiempo sin recaudo>
CAUSA: CAU-xx | <detalle>
Acción correctiva: <…>
Prevención: <acción propuesta> | ¿Abrir Problema en GLPI? <sí/no>
Revisión posterior: <fecha, máx. 2 días hábiles>
```

## [ESPERA]
```
[ESPERA] hh:mm
Se requiere de: <usuario/cliente/proveedor>
Qué:            <información o acción>
Solicitado por: <canal> a las <hh:mm>
Recordatorio:   <fecha hh:mm (24 h)>
```

## [RECORDATORIO]
```
[RECORDATORIO n.º 1/2] fecha hh:mm
Contacté a <quién> por <canal>: <respuesta / sin respuesta>
Siguiente: <recordatorio 2 a las 48 h / cierre a las 72 h>
```

## [CIERRE-SIN-RESPUESTA]
```
[CIERRE-SIN-RESPUESTA] fecha hh:mm
Sin respuesta tras recordatorios del <fecha> y <fecha>.
Se informa al usuario por <canal> que puede reabrir el caso respondiendo con <dato requerido>.
```

## [CAMBIO-PLAN]
```
[CAMBIO-PLAN] fecha hh:mm
Cambio:      <qué se instala/actualiza/ejecuta>
Versión:     <anterior> → <nueva>
Alcance:     <estaciones/carriles>
Ventana:     <fecha hh:mm> (lun–jue antes de 16:00)
Aprobó:      <quién, cómo>
Acompañan:   <Desarrollo / Pruebas si es script>
Reversión:   <cómo volver a la versión anterior>
Registro:    <referencia en el control de despliegues>
```

## [CAMBIO-EJEC]
```
[CAMBIO-EJEC] hh:mm
Ejecutado:   <hh:mm inicio–fin>
Verificación: <pruebas posteriores y resultado>
Incidencias: <ninguna / …>
Estado:      <exitoso / revertido>
```

## [ACT]
```
[ACT] hh:mm
Actividad:  <monitoreo / validación / mantenimiento>
Alcance:    <estaciones, aplicaciones, BD>
Resultado:  <sin novedad | hallazgo → incidencia #<n.º>>
```

## [TURNO]
```
[TURNO] hh:mm (privado)
Entrego a:  <turno / técnico>
Estado:     <dónde va el caso>
Falta:      <qué queda pendiente>
Compromiso: <próximo paso> antes de <hh:mm>
Ojo:        <riesgo o dato que el siguiente turno debe saber>
```

