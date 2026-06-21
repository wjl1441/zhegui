@echo off
cd /d "%~dp0"
set ZHEGUI_PORT=8010
echo.
echo   ZheGui - Kao Gong Bei Kao AI Zhu Shou
echo.
echo   Project: %CD%
echo   http://localhost:%ZHEGUI_PORT%
echo   Ctrl+C to stop
echo.
python server.py
pause
