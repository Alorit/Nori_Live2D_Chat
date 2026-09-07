@echo off
chcp 65001 >nul
cd /d "%~dp0"
call run.bat --no-pet %*
