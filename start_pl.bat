@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\streamlit.exe" (
    echo Virtual environment not found.
    echo Run install.bat first.
    pause
    exit /b 1
)

echo Starting Linear Cutting Calculator (Polish)...
call ".venv\Scripts\streamlit.exe" run app_pl.py
echo.
echo  Version 1.0
pause