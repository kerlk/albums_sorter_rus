@echo off
chcp 65001 >nul
setlocal

:: Определяем путь к скрипту
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH="C:\Users\%username%\albums_sorter_rus\music_organizer.py""

:: Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: Python не найден в PATH
    echo Установите Python с https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Запускаем скрипт. Если передан аргумент, используем его как путь,
:: иначе передаём текущую директорию.
if "%~1"=="" (
    set "MUSIC_PATH=%CD%"
) else (
    set "MUSIC_PATH=%~1"
)

python "%SCRIPT_PATH%" "%MUSIC_PATH%"

:: Сохраняем код ошибки
set "EXIT_CODE=%ERRORLEVEL%"

:: Пауза, если окно запущено двойным кликом (всегда делаем паузу)
echo.
echo Нажмите любую клавишу для выхода...
pause >nul

exit /b %EXIT_CODE%
