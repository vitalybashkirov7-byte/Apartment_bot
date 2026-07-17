@echo off
REM Скрипт запуска Telegram-бота поиска квартир в Новосибирске

echo ========================================
echo Telegram-бот поиска квартир в Новосибирске
echo ========================================
echo.

REM Проверка переменной окружения
if "%TELEGRAM_BOT_TOKEN%"=="" (
    echo Ошибка: Не установлена переменная окружения TELEGRAM_BOT_TOKEN
    echo.
    echo Установите токен:
    echo set TELEGRAM_BOT_TOKEN=ваш_токен
    echo.
    echo Или создайте файл .env с содержимым:
    echo TELEGRAM_BOT_TOKEN=ваш_токен
    echo.
    pause
    exit /b 1
)

REM Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Ошибка: Python не найден
    echo Установите Python 3.10+ с https://python.org
    pause
    exit /b 1
)

REM Установка зависимостей
echo Установка зависимостей...
pip install -r requirements.txt
if errorlevel 1 (
    echo Ошибка при установке зависимостей
    pause
    exit /b 1
)

echo.
echo Запуск бота...
echo Нажмите Ctrl+C для остановки
echo.

REM Запуск бота
python main.py

pause
