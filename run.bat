@echo off
chcp 65001 > nul
echo =========================================================
echo    EconoMetrics AI - Evaluador de Rentabilidad
echo    Iniciando configuracion para Windows...
echo =========================================================

REM Verificar instalacion de Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado o no se encuentra en el PATH.
    echo Por favor instala Python 3.10 o superior marcando "Add Python to PATH":
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Crear entorno virtual si no existe
if not exist "venv" (
    echo Creando entorno virtual (venv)...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
    echo Instalando dependencias de requirements.txt...
    call venv\Scripts\python.exe -m pip install --upgrade pip
    call venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo.
echo =========================================================
echo    Servidor activo en: http://localhost:8000
echo    Control Operativo:  http://localhost:8000/tracker.html
echo =========================================================
echo Presiona Ctrl + C en esta ventana para detener el servidor.
echo.

REM Intentar abrir el navegador automaticamente
start http://localhost:8000

REM Iniciar FastAPI / Uvicorn
venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000 --reload
pause
