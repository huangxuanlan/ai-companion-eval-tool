@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Longform Demo

echo.
echo ============================================================
echo   Longform Demo Launcher
echo ============================================================
echo.

set "TAILSCALE_PUBLIC_URL="
set "TAILSCALE_LOG=%TEMP%\longform_funnel_%RANDOM%%RANDOM%.log"
set "TAILSCALE_CLEANUP=0"

REM -- Check Python --
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)
echo [OK] Python found

REM -- Kill old process on port 8000 --
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo [..] Killing old process on port 8000, PID=%%a
    taskkill /PID %%a /F >nul 2>&1
    timeout /t 2 /nobreak >nul
)

REM -- Set demo mode --
set LONGFORM_PUBLIC_DEMO_MODE=1
echo [OK] LONGFORM_PUBLIC_DEMO_MODE=1

REM -- Start server --
echo [..] Starting server on port 8000...
start /B "" python "%~dp0server\main.py" >"%~dp0server-demo.log" 2>&1

REM -- Wait for server ready --
echo [..] Waiting for server...
REM -- Health check (retry up to 3 times) --
set HEALTH_OK=0
for /L %%i in (1,1,3) do (
    if !HEALTH_OK! equ 0 (
        curl.exe -s -o nul -w "" http://127.0.0.1:8000/ >nul 2>&1
        if !ERRORLEVEL! equ 0 set HEALTH_OK=1
        if !HEALTH_OK! equ 0 timeout /t 2 /nobreak >nul
    )
)
if !HEALTH_OK! equ 0 (
    echo [WARN] Server may not be ready. Check server-demo.log
    echo.
    type "%~dp0server-demo.log" 2>nul
    echo.
    pause
    exit /b 1
)
echo [OK] Server is running

REM -- Open browser --
echo [OK] Opening browser...
start "" "http://localhost:8000"

echo.
echo ============================================================
echo   Demo mode active
echo   Local:  http://localhost:8000
echo   Write operations blocked, /docs disabled
echo ============================================================
echo.

REM -- Check Tailscale --
where tailscale >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Tailscale not found, skipping Funnel.
    echo        For local demo, use http://localhost:8000
    echo.
    echo Press any key to stop server and exit...
    pause >nul
    goto CLEANUP
)

echo Starting Tailscale Funnel on port 8000...
echo.

call :START_FUNNEL
set "FUNNEL_EXIT=!ERRORLEVEL!"

if "!FUNNEL_EXIT!"=="0" (
    if defined TAILSCALE_PUBLIC_URL (
        echo [OK] Public URL:
        echo      !TAILSCALE_PUBLIC_URL!
        echo.
    ) else (
        echo [WARN] Funnel started, but URL could not be parsed automatically.
        echo        Run "tailscale funnel status" if you need to inspect it.
        echo.
    )
    echo Press any key to stop demo and close Funnel...
    pause >nul
    goto CLEANUP
)

echo [WARN] Funnel did not start. Local demo is still available:
echo        http://localhost:8000
echo.
echo Press any key to stop server and exit...
pause >nul
goto CLEANUP

:START_FUNNEL
call :RUN_FUNNEL
set "FUNNEL_EXIT=!ERRORLEVEL!"
if "!FUNNEL_EXIT!"=="0" (
    set "TAILSCALE_CLEANUP=1"
    call :CAPTURE_FUNNEL_URL
    exit /b 0
)

findstr /C:"listener already exists for port 443" "!TAILSCALE_LOG!" >nul 2>&1
if "!ERRORLEVEL!"=="0" (
    echo [WARN] Existing Tailscale HTTPS listener detected on port 443. Clearing it and retrying...
    set "TAILSCALE_CLEANUP=1"
    call :CLEAR_HTTPS_LISTENER
    call :RUN_FUNNEL
    set "FUNNEL_EXIT=!ERRORLEVEL!"
    if "!FUNNEL_EXIT!"=="0" (
        set "TAILSCALE_CLEANUP=1"
        call :CAPTURE_FUNNEL_URL
        exit /b 0
    )
)

findstr /C:"Access is denied" "!TAILSCALE_LOG!" >nul 2>&1
if "!ERRORLEVEL!"=="0" (
    echo [ERROR] Tailscale access denied. Please run start_demo.bat as Administrator.
    echo.
    type "!TAILSCALE_LOG!"
    exit /b 1
)

echo [WARN] Tailscale Funnel failed to start.
echo.
type "!TAILSCALE_LOG!"
exit /b 1

:RUN_FUNNEL
tailscale funnel --bg 8000 > "!TAILSCALE_LOG!" 2>&1
exit /b %ERRORLEVEL%

:CAPTURE_FUNNEL_URL
set "TAILSCALE_PUBLIC_URL="
for /f "tokens=1 delims= " %%a in ('tailscale funnel status ^| findstr /B /C:"https://"') do (
    if not defined TAILSCALE_PUBLIC_URL set "TAILSCALE_PUBLIC_URL=%%a"
)
if defined TAILSCALE_PUBLIC_URL exit /b 0

for /f "tokens=1 delims= " %%a in ('findstr /B /C:"https://" "!TAILSCALE_LOG!"') do (
    if not defined TAILSCALE_PUBLIC_URL set "TAILSCALE_PUBLIC_URL=%%a"
)
exit /b 0

:CLEAR_HTTPS_LISTENER
tailscale funnel --https=443 off >nul 2>&1
tailscale serve --https=443 off >nul 2>&1
exit /b 0

:CLEANUP
echo.
echo [..] Cleaning up...

if exist "!TAILSCALE_LOG!" del /q "!TAILSCALE_LOG!" >nul 2>&1
if "!TAILSCALE_CLEANUP!"=="1" call :CLEAR_HTTPS_LISTENER >nul 2>&1

REM -- Kill server --
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo [OK] Done.
echo.
pause
