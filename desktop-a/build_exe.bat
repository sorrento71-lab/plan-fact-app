@echo off
rem ============================================================
rem  Build Plan-Fakt.exe (prototype "variant A"), PyInstaller one-dir.
rem  Result: desktop-a\dist\<EXE_NAME>\<EXE_NAME>.exe
rem
rem  NOTE: this .bat is intentionally ASCII-only: Cyrillic text in a .bat
rem  breaks cmd.exe parsing, and the exe name is taken from planfact.spec.
rem ============================================================
chcp 65001 > nul
setlocal
title Plan-Fakt - build exe
cd /d "%~dp0"

set "TEMP=C:\plan-fact-app\.tmp"
set "TMP=C:\plan-fact-app\.tmp"
if not exist "%TEMP%" mkdir "%TEMP%"

set "PY=%~dp0..\.venv-desktop\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] Interpreter not found: %PY%
    pause
    exit /b 1
)

echo [1/4] Checking sources ...

if not exist "%~dp0..\backend\app.py" (
    echo [ERROR] backend\app.py not found next to desktop-a.
    pause
    exit /b 1
)

if not exist "%~dp0webapp\index.html" (
    echo [!] Frontend static not built - building into desktop-a\webapp ...
    call :build_web
)

if not exist "%~dp0webapp\index.html" (
    echo [ERROR] Could not build the frontend static into %~dp0webapp
    echo         Build it manually:
    echo           cd C:\plan-fact-app\frontend
    echo           set BUILD_PATH=C:\plan-fact-app\desktop-a\webapp
    echo           npm.cmd run build
    pause
    exit /b 1
)

dir /b "%~dp0..\*A3.xlsx" > nul 2>&1
if errorlevel 1 (
    echo [!] Warning: schedule xlsx ^(graph form A3^) not found next to desktop-a
    echo     The build continues, but schedule features may be unavailable.
)

echo [2/4] Cleaning previous build output ...
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist" rmdir /s /q "%~dp0dist"

echo [3/4] Running PyInstaller (takes a few minutes) ...
echo        Build log: %~dp0build_exe.log
"%PY%" -m PyInstaller --noconfirm --distpath "%~dp0dist" --workpath "%~dp0build" "%~dp0planfact.spec" > "%~dp0build_exe.log" 2>&1
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [ERROR] PyInstaller failed with code %RC%
    echo Last log lines:
    powershell -NoProfile -Command "Get-Content -Tail 25 '%~dp0build_exe.log'"
    pause
    exit /b %RC%
)

echo [4/4] Checking the result ...
if not exist "%~dp0dist" (
    echo [ERROR] dist folder was not created.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Done! Build output:
dir /b "%~dp0dist"
echo.
echo   Run the .exe from the folder above (double click).
echo   Exit code and details of the run are written to launcher.log
echo   inside that folder (the exe has no console window).
echo ============================================================
pause
exit /b 0

:build_web
pushd "%~dp0..\frontend"
set "BUILD_PATH=%~dp0webapp"
set "CI=false"
call npm.cmd run build
popd
exit /b 0
