@echo off
rem Build the desktop Plan-Fact (variant B) into dist\Plan-Fact\Plan-Fact.exe
rem NOTE: keep this file ASCII-only - Cyrillic text breaks cmd.exe line parsing.
chcp 65001 >nul
setlocal
set "HERE=%~dp0"
set "PY=%HERE%..\.venv-desktop\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%HERE%"

echo [1/3] Checking sources...
"%PY%" -c "import sys; sys.path.insert(0,'.'); import planfact.core; print('kernel ok:', planfact.core.BACKEND_DIR)"
if errorlevel 1 goto :failed

echo [2/3] Cleaning build/dist...
if exist "%HERE%build" rmdir /s /q "%HERE%build"
if exist "%HERE%dist" rmdir /s /q "%HERE%dist"

echo [3/3] Running PyInstaller (takes a few minutes)...
"%PY%" -m PyInstaller --noconfirm --clean "%HERE%planfact-b.spec" > "%HERE%build_exe.log" 2>&1
if errorlevel 1 goto :failed

if not exist "%HERE%dist\План-Факт\План-Факт.exe" goto :failed

echo.
echo Done: %HERE%dist\План-Факт\План-Факт.exe
echo Keep the whole dist\План-Факт folder together (one-dir build).
exit /b 0

:failed
echo.
echo BUILD FAILED. Tail of build_exe.log:
powershell -NoProfile -Command "if (Test-Path '%HERE%build_exe.log') { Get-Content '%HERE%build_exe.log' -Tail 25 }"
exit /b 1
