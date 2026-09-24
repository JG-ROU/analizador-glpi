# Instrucciones del proyecto – Analizador GLPI

Antes de cualquier acción, lee completo `spec/LEEME_PRIMERO.md` y sigue su orden de lectura y su forma de trabajo.

- Especificación: `spec/docs/` · Catálogos reales: `spec/catalogos/` (no los modifiques salvo que se pida).
- Código: `core/` (lógica, sin Qt), `ui/` (PySide6), `assets/`, `data/muestras/` (generador de CSV ficticio), `tests/`.
- Entorno: `.venv`. Pruebas: `.venv\Scripts\python -m pytest`. Ejecutar: `.venv\Scripts\python main.py`.
- Nunca uses datos reales en pruebas ni los subas al repositorio.
