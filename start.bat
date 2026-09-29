@echo off
chcp 1251 > nul
title План-Факт: запуск серверов
echo ============================================
echo   Запуск серверов "План-Факт"
echo ============================================
echo.

cd /d "%~dp0"

rem ---------- Проверка Node.js ----------
where node > nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Node.js не найден. Установите его: https://nodejs.org
    pause
    exit /b 1
)

rem ---------- Выбор Python: venv проекта или системный ----------
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
    set "PYTHON=py"
)

rem ---------- Проверка зависимостей Python ----------
"%PYTHON%" -c "import fastapi, uvicorn, sqlalchemy, pandas, openpyxl, xlrd" > nul 2>&1
if errorlevel 1 (
    echo Устанавливаю зависимости Python из requirements.txt...
    "%PYTHON%" -m pip install -r "%~dp0requirements.txt"
    echo.
)

rem ---------- npm-зависимости фронтенда (первый запуск) ----------
if not exist "%~dp0frontend\node_modules" (
    echo Устанавливаю npm-зависимости фронтенда...
    pushd "%~dp0frontend"
    call npm install
    popd
    echo.
)

rem ---------- Бэкенд (порт 8000) ----------
netstat -ano | findstr ":8000.*LISTENING" > nul 2>&1
if not errorlevel 1 (
    echo [OK] Бэкенд уже запущен на порту 8000
) else (
    echo Запускаю бэкенд: http://127.0.0.1:8000 ...
    pushd "%~dp0backend"
    start "План-Факт: Backend" /B "%PYTHON%" -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload > uvicorn.log 2>&1
    popd
    echo      Лог: backend\uvicorn.log
)

rem ---------- Фронтенд (порт 3000) ----------
netstat -ano | findstr ":3000.*LISTENING" > nul 2>&1
if not errorlevel 1 (
    echo [OK] Фронтенд уже запущен на порту 3000
) else (
    echo Запускаю фронтенд: http://127.0.0.1:3000 ...
    pushd "%~dp0frontend"
    start "План-Факт: Frontend" /B cmd /c "npm start > devserver.log 2>&1"
    popd
    echo      Лог: frontend\devserver.log
)

echo.
echo ============================================
echo   Готово!
echo     Фронтенд: http://127.0.0.1:3000
echo     API:      http://127.0.0.1:8000
echo   Остановка серверов: stop.bat
echo ============================================
ping -n 6 127.0.0.1 > nul
