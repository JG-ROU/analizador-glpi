# Cómo arrancar el proyecto

1. Instala Python 3.11 o 3.12 (python.org → "Install for current user" + "Add python.exe to PATH"), Git y VS Code.
2. Ejecuta `setup.bat` (crea `.venv`, instala dependencias y copia `config.ini`).
3. Ajusta en `config.ini` las franjas de turno a la malla real.
4. Abre la carpeta en VS Code (`code .`) e instala las extensiones recomendadas.
5. `git init` → `git add .` → `git commit -m "Especificación inicial"`.
6. En el panel de la IA escribe:
   > Lee CLAUDE.md y spec/LEEME_PRIMERO.md y entrega la primera respuesta que pide (resumen, preguntas, arquitectura y plan de la Fase 1). No escribas código todavía.
7. Responde sus preguntas, aprueba el plan y pide: "Desarrolla la Fase 1 tarea por tarea".
8. Por cada tarea: revisa, ejecuta pruebas (panel Testing), prueba con F5 y haz commit.
9. Para probar con datos reales: exporta desde GLPI una búsqueda de tickets en CSV (sección 03 de la especificación) y úsala solo en tu equipo.
