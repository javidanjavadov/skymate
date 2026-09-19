@echo off
cd /d "%~dp0"
title SkyMate
:loop
py run.py
echo SkyMate supervisor exited, restarting in 10 seconds... (close this window to stop)
timeout /t 10 /nobreak >nul
goto loop
