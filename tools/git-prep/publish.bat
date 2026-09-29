@echo off
chcp 1251 > nul
title План-Факт: публикация на GitHub
set "GIT=%LOCALAPPDATA%\Programs\PortableGit\bin\git.exe"
if not exist "%GIT%" set "GIT=git"
cd /d "%~dp0..\.."

echo ============================================
echo   Публикация проекта "План-Факт" на GitHub
echo ============================================
echo.
echo 1. Откройте github.com -^> New repository
echo 2. Имя: plan-fact-app,  видимость: Public
echo 3. НЕ ставьте галочки README / .gitignore / license
echo 4. Нажмите Create repository и скопируйте адрес
echo    вида https://github.com/ЛОГИН/plan-fact-app.git
echo.
set /p URL=Адрес репозитория: 
if "%URL%"=="" (
  echo Адрес не указан - выход.
  pause
  exit /b 1
)

"%GIT%" remote remove origin > nul 2>&1
"%GIT%" remote add origin "%URL%"
echo.
echo Отправляю ветку main. При первом входе откроется окно GitHub -
echo войдите в свой аккаунт и разрешите доступ.
echo.
"%GIT%" push -u origin main

echo.
if errorlevel 1 (
  echo НЕ УДАЛОСЬ отправить. Проверьте адрес репозитория и вход в GitHub.
) else (
  echo ГОТОВО: проект опубликован на GitHub.
)
pause
