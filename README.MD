# Analizador GLPI

Aplicativo de escritorio portable para Windows que convierte las exportaciones CSV de **GLPI 9.1.4** en indicadores confiables para un equipo de soporte de aplicaciones 24/7. Funciona sin internet y guarda los datos solo en el equipo, en una base SQLite.

**Estado:** Fase 1 terminada (importación, base de datos, KPIs, dashboard, novedades, responsables, configuración, historial y reportes REP-01 y REP-03). Las Fases 2 y 3 están descritas en [spec/docs/12_fases_y_criterios_de_aceptacion.md](spec/docs/12_fases_y_criterios_de_aceptacion.md).

## Qué hace (Fase 1)

- **Importa** la exportación de tickets de GLPI con autodetección de columnas, separador, codificación y formato de fecha. Guarda perfiles reutilizables y valida cada fila (verde / amarillo / rojo).
- **Detecta cambios entre importaciones:** escalamientos, soluciones, cierres, reaperturas, reasignaciones y cambios de prioridad. La exportación trae solo el estado actual; ver `spec/docs/03`, IMP-06.
- **Calcula KPIs** con semáforo, variación frente al período anterior y criticidad global: recibidos, resueltos, backlog, total gestionados, tasa de escalamiento, tiempo de resolución, SLA, resueltos sin cerrar, sin actualizar y tiempo en escalado.
- **Pantallas:** Dashboard, Importar, Novedades con detalle de ticket, Responsables, Configuración e Historial.
- **Reportes** REP-01 (Resumen de indicadores) y REP-03 (Responsables) en Excel y CSV.
- **Seguridad:** PIN con hash para todos los usuarios y permisos por perfil aplicados en la lógica. Un técnico solo ve sus propias métricas.
- **Respaldo automático** antes de cada importación y uno diario, con restauración desde la interfaz. Historial de cambios de solo inserción.

## Requisitos para desarrollar

- Windows 10/11, Python 3.11 o superior.
- `setup.bat` crea el entorno `.venv` e instala las dependencias de `requirements.txt`.

## Uso en desarrollo

| Acción | Comando |
|---|---|
| Ejecutar | `.venv\Scripts\python main.py` |
| Pruebas | `.venv\Scripts\python -m pytest` |
| Datos ficticios de prueba | `.venv\Scripts\python data\muestras\generador_glpi.py --tickets 300 --cortes 5 --errores 6` |
| Datos de volumen (CA-07) | `.venv\Scripts\python data\muestras\generador_glpi.py --tickets 20000 --desde 2021-09-01` |

Los CSV generados quedan en `data/muestras/generados/`, que no se sube al repositorio. **Nunca use datos reales en las pruebas.**

## Generar el ejecutable

```
build.bat            → dist\AnalizadorGLPI\AnalizadorGLPI.exe   (carpeta; recomendado)
build.bat onefile    → dist\AnalizadorGLPI.exe                  (un solo archivo)
```

`build.bat` corre primero todas las pruebas y no empaqueta si alguna falla.

- **Modo carpeta (`--onedir`, recomendado):** arranca en pocos segundos. Se copia la carpeta completa `dist\AnalizadorGLPI\` a cualquier ubicación o memoria USB.
- **Modo un solo archivo:** es más cómodo de copiar, pero en cada arranque se descomprime (varios segundos más) y algunos antivirus lo revisan con más recelo.

Al primer arranque se crean junto al ejecutable `config.ini`, `data\analizador.db`, `data\respaldos\`, `logs\app.log` y `exportaciones\`. No requiere instalación ni permisos de administrador.

## Estructura

```
main.py                 arranque: config, logs, BD + migraciones, respaldo, sesión, ventana
core/                   lógica sin Qt (se prueba sin interfaz)
  config.py, rutas.py, registro.py, reloj.py, turnos.py, seguridad.py, historial.py,
  parametros.py, configuracion.py, dominio.py, errores.py
  db/                   conexión, migraciones versionadas (migraciones/NNN_*.sql), semillas, respaldos
  fuentes/              FuenteDatos (interfaz) y fuente_csv.py
  importacion/          mapeo, validación, derivados, eventos y carga incremental
  analisis/             períodos, estadística, filtros, KPIs, semáforo, SLA, series, novedades, responsables
  reportes/             gráficos (matplotlib), Excel/CSV y catálogo REP-01 / REP-03
ui/                     PySide6: ventana, pantallas, componentes, hilos de trabajo
assets/estilos/         estilo QSS corporativo
data/muestras/          generador de CSV ficticios en formato GLPI
tests/                  pruebas pytest (lógica e interfaz)
spec/                   especificación del proyecto
```

## Documentación

- Manual de uso: [MANUAL_USUARIO.md](MANUAL_USUARIO.md)
- Especificación: [spec/LEEME_PRIMERO.md](spec/LEEME_PRIMERO.md) y [spec/docs/](spec/docs/)

## Cómo se construyó este proyecto

Este es un proyecto de **desarrollo asistido por IA**. La división del trabajo fue:

**Mi aporte (autor):**

- Identificación del problema operativo en un equipo de soporte de aplicaciones 24/7.
- Definición de requisitos, reglas de negocio, indicadores y umbrales.
- Estándares de tipificación, causas y plantillas de documentación.
- Criterios de evaluación de calidad y reglas de medición justa por técnico.
- Especificación funcional completa (`spec/`), con requisitos identificados y criterios de aceptación.
- Revisión, pruebas y validación con datos del contexto real.

**Apoyo de IA:**

- Estructuración de la especificación.
- Generación de código a partir de ella, por fases y con pruebas automáticas.
- Toda la salida de la IA fue revisada y aprobada antes de integrarse.

**Por qué así:** el objetivo es mostrar cómo convertir un problema de gestión en una solución de software mantenible. Primero se define qué medir y por qué; después, la IA acelera la construcción.

> Los datos incluidos son ficticios. El proyecto no contiene información de ninguna empresa ni credenciales.
