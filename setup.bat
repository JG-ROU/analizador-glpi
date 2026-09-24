@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (
  echo Creando entorno virtual...
  %PY% -m venv .venv || (echo ERROR: se requiere Python 3.11 o superior & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist config.ini copy config.ini.ejemplo config.ini
echo.
echo Listo. Abre la carpeta en VS Code:  code .
pause
