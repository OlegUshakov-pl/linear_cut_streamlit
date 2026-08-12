@echo off
setlocal

cd /d "%~dp0"

echo ============================================
echo  Linear Cutting Calculator installation
echo ============================================
echo.

if not exist ".venv" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Error: failed to create venv. Check your Python installation.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment already exists, skipping.
)

echo [2/3] Upgrading pip...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Error while upgrading pip.
    pause
    exit /b 1
)

echo [3/3] Installing dependencies from requirements.txt...
call ".venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo Error while installing dependencies.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Installation completed successfully!
echo  Run the application with:
echo      .\.venv\Scripts\streamlit run app.py
echo ============================================
echo  Version 1.0
pause