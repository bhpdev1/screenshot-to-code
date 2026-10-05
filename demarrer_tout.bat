@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title Screenshot-to-Code Launcher
cd /d "%~dp0"
echo Demarrage du Backend et du Frontend...
start "Screenshot-to-Code Backend" cmd /k "chcp 65001 >nul && set PYTHONIOENCODING=utf-8 && cd /d %~dp0backend && .\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 7001"
start "Screenshot-to-Code Frontend" cmd /k "cd /d %~dp0frontend && pnpm dev"
echo Les serveurs sont lances !
echo Ouverture de http://localhost:5173...
timeout /t 3 >nul
start http://localhost:5173
