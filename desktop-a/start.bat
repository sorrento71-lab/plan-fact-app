@echo off
rem ============================================================
rem  Plan-Fakt - prototype "variant A": separate window, no browser
rem  Starts launcher.py with the interpreter from .venv-desktop.
rem
rem  NOTE: this .bat is intentionally ASCII-only. Cyrillic text in a
rem  .bat file breaks cmd.exe parsing (the launcher itself prints
rem  Russian/UTF-8 text - see chcp 65001 below and desktop-a\launcher.log).
rem ============================================================
chcp 65001 > nul
setlocal
title Plan-Fakt - prototype A
cd /d "%~dp0"

set "DESKTOP_A=%~dp0"
set "VENV=%DESKTOP_A%..\.venv-desktop\Scripts"
set "PYW=%VENV%\pythonw.exe"
set "PY=%VENV%\python.exe"

if not exist "%PYW%" set "PYW="
if not exist "%PY%" set "PY="

if not defined PY if not defined PYW (
    echo [ERROR] Python interpreter for the prototype not found.
    echo         Expected: %VENV%\python.exe
    pause
    exit /b 1
)

rem ---- With arguments run in this console window, so the output is visible ----
if not "%~1"=="" goto console

rem ---- Normal start: pythonw.exe, no extra console window ----
if defined PYW (
    echo Starting Plan-Fakt prototype A ...
    echo   interpreter: %PYW%
    echo   log file:    %DESKTOP_A%launcher.log
    start "" "%PYW%" "%DESKTOP_A%launcher.py"
    exit /b 0
)

"%PY%" "%DESKTOP_A%launcher.py"
set "RC=%ERRORLEVEL%"
echo.
echo Prototype finished, exit code %RC%.
pause
exit /b %RC%

:console
"%PY%" "%DESKTOP_A%launcher.py" %*
set "RC=%ERRORLEVEL%"
echo.
echo Exit code: %RC%
pause
exit /b %RC%
