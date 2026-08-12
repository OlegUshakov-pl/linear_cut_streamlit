@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\streamlit.exe" (
    echo Nie znaleziono środowiska wirtualnego.
    echo Uruchom najpierw install.bat.
    pause
    exit /b 1
)

echo Uruchamianie Kalkulatora cięcia liniowego (polski)...
call ".venv\Scripts\streamlit.exe" run app_pl.py
echo.
echo  Wersja 1.0
pause