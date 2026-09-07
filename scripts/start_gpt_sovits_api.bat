@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set "RT=D:\GPT-SoVITS-v2pro-20250604-nvidia50"
if not exist "%RT%\runtime\pythonw.exe" (
    echo GPT-SoVITS runtime not found: %RT%
    pause
    exit /b 1
)
echo Starting GPT-SoVITS API silently (view logs in the GUI console tab) ...
start "" "%RT%\runtime\pythonw.exe" "%~dp0gpt_sovits_service.py" "%RT%" 127.0.0.1 9880 "GPT_SoVITS\configs\tts_infer.yaml" "%CD%\data\logs\gpt_sovits.log" "%CD%\data\gpt_sovits.pid"
exit /b 0
