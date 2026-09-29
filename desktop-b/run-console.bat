@echo off
rem Same as run.bat, but with a console window: kernel messages and errors are visible.
rem NOTE: keep this file ASCII-only - Cyrillic text breaks cmd.exe line parsing.
chcp 65001 >nul
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\.venv-desktop\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%HERE%"
"%PY%" "%HERE%run.py" %*
