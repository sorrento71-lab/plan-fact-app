@echo off
rem Desktop Plan-Fact (variant B). Opens its own window, no console.
rem For diagnostics (visible kernel messages and errors) use run-console.bat
rem NOTE: keep this file ASCII-only - Cyrillic text breaks cmd.exe line parsing.
chcp 65001 >nul
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\.venv-desktop\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"
cd /d "%HERE%"
start "" "%PY%" "%HERE%run.py" %*
