@echo off
title IoT Sensor Network — Stop
color 0C

echo.
echo  Stopping IoT Sensor Network...
echo.

:: Kill all sensor node python processes launched by launch_nodes
taskkill /F /FI "WINDOWTITLE eq IoT Hub*"    /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq IoT Nodes*"  /T >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq IoT Dashboard*" /T >nul 2>&1

:: Kill any lingering streamlit or sensor_node processes
wmic process where "commandline like '%%sensor_node%%'" delete >nul 2>&1
wmic process where "commandline like '%%streamlit%%run%%app%%'" delete >nul 2>&1

:: Clean up PID files
if exist "data\pids\" (
    del /Q "data\pids\*.json" >nul 2>&1
)

echo  All processes stopped.
echo.
pause
