@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\streamlit.exe" (
    echo Виртуальное окружение не найдено.
    echo Сначала запустите install.bat.
    pause
    exit /b 1
)

echo Запуск Калькулятора линейного раскроя (русский)...
call ".venv\Scripts\streamlit.exe" run app_ru.py
echo.
echo  Версия 1.0
pause