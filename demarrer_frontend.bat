@echo off
title Screenshot-to-Code Frontend
cd /d "%~dp0frontend"
echo Lancement du frontend sur http://localhost:5173...
call pnpm dev
pause
