@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  Nori AI - console mode (visible logs for debugging)
echo ============================================================
call .venv\Scripts\activate.bat
python main.py %*
pause
