# 10 – Requisitos no funcionales

| ID | Requisito | Verificación |
|---|---|---|
| RNF-01 | **Portable:** un `AnalizadorGLPI.exe` (PyInstaller) para Windows 10/11 de 64 bits; corre desde carpeta local o USB, sin instalación ni permisos de administrador | PC limpio |
| RNF-02 | **Offline:** sin internet; íconos, estilos y fuentes incluidos | Red deshabilitada |
| RNF-03 | **Carpetas junto al .exe:** `data/analizador.db`, `data/respaldos/`, `logs/`, `exportaciones/`, `config.ini`. Se crean si faltan | Primer arranque |
| RNF-04 | **Respaldo automático** de la BD antes de cada importación y diario; retención configurable (30); restauración desde la interfaz con respaldo previo | Prueba |
| RNF-05 | **Rendimiento:** importar 20.000 tickets en menos de 30 s (lectura por bloques); dashboard en menos de 2 s con 5 años de datos; reportes PDF en menos de 15 s | Datos ficticios de volumen |
| RNF-06 | **UI fluida:** importación, cálculo de hallazgos y generación de reportes en hilos de trabajo (QThread) con barra de progreso; la interfaz nunca se congela | Prueba manual |
| RNF-07 | **Seguridad:** sin credenciales de GLPI ni de correo almacenadas; PIN del coordinador con hash (bcrypt o argon2); permisos por perfil aplicados en `core/`, no solo ocultando botones | Pruebas |
| RNF-08 | **Datos personales:** solo locales; opción de anonimizar solicitantes en exportaciones | Prueba |
| RNF-09 | **Auditoría:** historial de solo inserción para evaluaciones, parámetros, KPIs y catálogos | Intentar modificar el historial |
| RNF-10 | **Configuración:** `config.ini` (rutas, franjas de turno, separador por defecto, nivel de log) + tabla `parametro` (umbrales editables en pantalla) | Revisión |
| RNF-11 | **Errores:** mensajes en español; detalle en `logs/app.log` con rotación | Provocar errores |
| RNF-12 | **Accesibilidad:** semáforos siempre con texto o ícono; contraste suficiente; tamaños de fuente legibles | Revisión visual |
| RNF-13 | **Mantenibilidad:** `core/` sin dependencias de Qt; pruebas pytest de fórmulas, reglas HAL y puntajes CAL; migraciones versionadas; código documentado | Revisión |
| RNF-14 | **Preparado para API:** `core/fuentes/` define una interfaz `FuenteDatos` (`obtener_tickets(desde, hasta)`, `obtener_seguimientos(ids)`); el CSV es la primera implementación | Revisión |
| RNF-15 | **Versión:** visible en "Acerca de"; al abrir una BD de una versión anterior se migra con respaldo previo | Prueba |
