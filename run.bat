@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  Nori AI - One-click launcher
echo ============================================================
echo  Console window will close; all logs are inside the GUI:
echo  Nori Control Panel - Console tab.
echo ============================================================

if not exist .venv (
    echo [0/1] Python environment missing, running setup_venv.bat ...
    call setup_venv.bat
    if errorlevel 1 (
        echo setup_venv.bat failed.
        pause
        exit /b 1
    )
)

echo [1/1] Starting Nori control panel (Heart / GPT-SoVITS / Live2D start silently) ...
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py" %*
) else (
    start "" ".venv\Scripts\python.exe" "%~dp0main.py" %*
)
exit /b 0
