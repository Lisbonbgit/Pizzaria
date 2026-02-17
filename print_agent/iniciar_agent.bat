@echo off
title Pizzaria Print Agent
color 0A

echo.
echo ========================================
echo   PIZZARIA PRINT AGENT - Windows
echo ========================================
echo.

REM Verificar se Python está instalado
python --version > nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado!
    echo.
    echo Por favor instale Python 3.8 ou superior:
    echo https://www.python.org/downloads/
    echo.
    echo Durante a instalacao, marque a opcao:
    echo "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

REM Verificar se requests está instalado
python -c "import requests" > nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias...
    pip install requests
    echo.
)

REM Executar o agent
echo Iniciando Print Agent...
echo.
python "%~dp0print_agent.py"

pause
