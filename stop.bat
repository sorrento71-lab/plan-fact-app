@echo off
chcp 1251 > nul
title План-Факт: остановка серверов
echo ============================================
echo   Остановка серверов "План-Факт"
echo ============================================
echo.

rem ---------- Бэкенд (порт 8000) ----------
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000.*LISTENING"') do (
    taskkill /F /T /PID %%p > nul 2>&1 && echo [OK] Остановлен бэкенд (PID %%p)
)

rem ---------- Фронтенд (порт 3000) ----------
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000.*LISTENING"') do (
    taskkill /F /T /PID %%p > nul 2>&1 && echo [OK] Остановлен фронтенд (PID %%p)
)

echo.
echo Готово. Серверы остановлены.
echo.
pause
