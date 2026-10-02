@echo off
title Reproductor Local Completo (M4A / LRC / TTML)
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Iniciando Reproductor Local Completo
echo ============================================================
echo.

echo [1/3] Verificando dependencias necesarias...
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo [AVISO] Ocurrio un detalle instalando dependencias. Continuando...
)

echo.
echo [2/3] Abriendo navegador en http://localhost:8000 ...
start http://localhost:8000

echo.
echo [3/3] Iniciando servidor de streaming y letras...
echo Presiona Ctrl+C para detener el servidor en cualquier momento.
echo.
python servidor_completo.py

pause
