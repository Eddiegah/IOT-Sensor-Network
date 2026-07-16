@echo off
title IoT Sensor Network — Launcher
color 0A

echo.
echo  ============================================
echo   IoT Sensor Network Simulator
echo  ============================================
echo.

:: ── Check Mosquitto is running ──────────────────────────────────────────────
echo  [1/4] Checking Mosquitto broker...
netstat -an | findstr ":1883" | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Mosquitto is not running on port 1883.
    echo  Fix: Open PowerShell as Administrator and run:
    echo        net start mosquitto
    echo.
    pause
    exit /b 1
)
echo        OK - Mosquitto listening on port 1883

:: ── Start hub ────────────────────────────────────────────────────────────────
echo  [2/4] Starting hub...
start "IoT Hub" cmd /k "cd /d "%~dp0" && venv\Scripts\python.exe src\hub.py"
timeout /t 2 /nobreak >nul
echo        OK - Hub started

:: ── Start sensor nodes ────────────────────────────────────────────────────────
echo  [3/4] Starting sensor nodes...
start "IoT Nodes" cmd /k "cd /d "%~dp0" && venv\Scripts\python.exe src\launch_nodes.py"
timeout /t 3 /nobreak >nul
echo        OK - Sensor nodes started

:: ── Start dashboard ──────────────────────────────────────────────────────────
echo  [4/4] Starting dashboard...
start "IoT Dashboard" cmd /k "cd /d "%~dp0" && venv\Scripts\streamlit.exe run app.py"
timeout /t 3 /nobreak >nul
echo        OK - Dashboard starting...

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo  ============================================
echo   All systems running.
echo   Dashboard: http://localhost:8501
echo  ============================================
echo.
echo  To demo fault detection, open a new terminal and run:
echo    venv\Scripts\python.exe src/fault_injector.py --kill node_3
echo    venv\Scripts\python.exe src/fault_injector.py --revive node_3
echo.
echo  Close this window whenever you're done.
echo  (The hub, nodes, and dashboard windows stay open until you close them.)
echo.

:: Open browser automatically
timeout /t 4 /nobreak >nul
start http://localhost:8501

pause
