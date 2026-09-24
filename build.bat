@echo off
rem Genera el ejecutable portable del Analizador GLPI con PyInstaller (RNF-01).
rem   build.bat           -> carpeta dist\AnalizadorGLPI\ (recomendado: arranca rapido)
rem   build.bat onefile   -> un solo archivo dist\AnalizadorGLPI.exe (arranca mas lento)
rem Primero corre las pruebas; si alguna falla, no empaqueta.

cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo ERROR: no existe el entorno .venv. Ejecute primero setup.bat
  exit /b 1
)

echo === Pruebas ===
.venv\Scripts\python -m pytest -q
if errorlevel 1 (
  echo ERROR: hay pruebas que fallan. No se genera el ejecutable.
  exit /b 1
)

set MODO=--onedir
if /i "%1"=="onefile" set MODO=--onefile

echo === Empaquetando (%MODO%) ===
.venv\Scripts\python -m PyInstaller main.py ^
  --name AnalizadorGLPI ^
  %MODO% ^
  --windowed ^
  --noconfirm ^
  --clean ^
  --add-data "config.ini.ejemplo;." ^
  --add-data "assets;assets" ^
  --add-data "core\db\migraciones;core\db\migraciones" ^
  --add-data "spec\catalogos;spec\catalogos" ^
  --collect-data tzdata ^
  --exclude-module tkinter ^
  --exclude-module pytest ^
  --exclude-module pytestqt ^
  --exclude-module IPython
if errorlevel 1 (
  echo ERROR: PyInstaller no pudo generar el ejecutable. Revise los mensajes anteriores.
  exit /b 1
)

echo.
if /i "%1"=="onefile" (
  echo Listo: dist\AnalizadorGLPI.exe
) else (
  echo Listo: dist\AnalizadorGLPI\AnalizadorGLPI.exe  ^(copie la carpeta completa^)
)
echo Al primer arranque se crean junto al ejecutable: config.ini, data\, logs\ y exportaciones\
