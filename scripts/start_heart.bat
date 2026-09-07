@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Starting Nori Heart silently (view logs in the GUI console tab) ...
if not exist .venv\Scripts\pythonw.exe (
    echo pythonw.exe not found. Please run setup_venv.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0..\heart.py"
exit /b 0
