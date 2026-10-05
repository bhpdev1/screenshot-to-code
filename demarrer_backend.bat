@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title Screenshot-to-Code Backend
cd /d "%~dp0backend"
echo Lancement du backend sur http://127.0.0.1:7001...
call .\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 7001
pause
