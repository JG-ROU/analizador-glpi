# 11 – Arquitectura y estructura

## Stack (definido por el usuario; propone ajustes solo si hay una razón fuerte)
| Capa | Tecnología |
|---|---|
| Interfaz | PySide6 (Qt 6), con estilos QSS corporativos en `assets/estilos/` |
| Gráficos | matplotlib embebido (FigureCanvasQTAgg), reutilizado en los PDF |
| Lógica | Python 3.11+ (paquete `core/`) |
| Datos | SQLite (sqlite3 o SQLAlchemy 2.x), modo WAL, migraciones versionadas |
| Importación y análisis | pandas (`read_csv` con `chunksize`) |
| Exportación | openpyxl (Excel), pandas (CSV), fpdf2 (PDF) |
| Seguridad | bcrypt o argon2-cffi para el PIN |
| Pruebas | pytest (+ pytest-qt opcional para la interfaz) |
| Empaquetado | PyInstaller (`--onefile --windowed`), script `build.bat` |

## Estructura de carpetas
```
GLPI_Analizador/
├── main.py                    # arranque: config, logs, BD + migraciones, respaldo, ventana
├── config.ini.ejemplo
├── core/
│   ├── config.py
│   ├── db/                    # conexión, esquema, migraciones, semilla (desde spec/catalogos)
│   ├── fuentes/               # FuenteDatos (interfaz), fuente_csv.py, fuente_api.py (futuro)
│   ├── importacion/           # mapeo, validación, carga incremental, derivados (IMP-xx)
│   ├── analisis/
│   │   ├── kpis.py            # motor de KPIs configurables (KPI-00) + predefinidos
│   │   ├── sla.py
│   │   ├── hallazgos.py       # HAL-xx
│   │   ├── calidad.py         # CAL-xx: puntaje, precalificación, ranking
│   │   └── snapshot.py
│   ├── reportes/              # REP-xx: excel.py, pdf.py, csv.py, graficos.py, segmov.py
│   ├── notificaciones.py      # NOT-xx y .eml
│   ├── historial.py
│   └── seguridad.py
├── ui/
│   ├── ventana_principal.py
│   ├── pantallas/             # una por PAN-xx
│   ├── componentes/           # tarjetas KPI, tabla filtrable, checkbox tri-estado, gráficos
│   └── hilos.py               # QThread para tareas largas
├── assets/                    # íconos, estilos QSS, logo
├── data/
│   ├── muestras/              # generador de CSV ficticios (formato GLPI) para pruebas y demo
│   └── (analizador.db se crea aquí; no va al repositorio)
├── tests/
├── spec/                      # esta especificación (no modificar sin pedirlo)
├── build.bat
├── README.md
└── MANUAL_USUARIO.md          # instalación, configuración, importación, uso por módulo
```

## Principios
- `ui/` nunca calcula: llama funciones de `core/` y muestra el resultado.
- Todo cálculo es una función pura y probada: recibe un DataFrame o una consulta más filtros y devuelve un resultado.
- Cada importación va en una sola transacción. Después dispara, en un hilo: derivados → hallazgos → snapshot (si aplica) → notificaciones.
- Los filtros de KPIs se traducen a SQL parametrizado; no se usa `eval`.
