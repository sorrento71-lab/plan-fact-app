@echo off
chcp 1251 > nul
title План-Факт: отправка проекта на GitHub
set "GIT=%LOCALAPPDATA%\Programs\PortableGit\bin\git.exe"
if not exist "%GIT%" set "GIT=git"
set "DEFAULT=https://github.com/sorrento71-lab/plan-fact-app.git"
cd /d "%~dp0..\.."

echo ============================================
echo   Отправка проекта "План-Факт" на GitHub
echo ============================================
echo.
echo Если репозиторий ещё не создан:
echo   github.com/new  -^>  имя plan-fact-app  -^>  Public  -^>  Create repository
echo   (галочки README / .gitignore / license НЕ ставить)
echo.
set /p URL=Адрес репозитория [Enter = %DEFAULT%]: 
if "%URL%"=="" set "URL=%DEFAULT%"

"%GIT%" remote remove origin > nul 2>&1
"%GIT%" remote add origin "%URL%"
echo.
echo Отправляю ветку main на %URL%
echo Если откроется окно входа в GitHub - войдите и разрешите доступ.
echo.
"%GIT%" push -u origin main

echo.
if errorlevel 1 (
  echo.
  echo НЕ УДАЛОСЬ ОТПРАВИТЬ. Проверьте:
  echo   1) репозиторий создан на github.com и адрес скопирован верно;
  echo   2) вход в GitHub выполнен (окно входа могло не открыться -
  echo      тогда запустите файл ещё раз).
) else (
  echo.
  echo ГОТОВО: проект опубликован на GitHub.
)
pause
