#!/bin/bash
# Скрипт запуска Telegram-бота поиска квартир в Новосибирске

echo "========================================"
echo "Telegram-бот поиска квартир в Новосибирске"
echo "========================================"
echo ""

# Проверка переменной окружения
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "Ошибка: Не установлена переменная окружения TELEGRAM_BOT_TOKEN"
    echo ""
    echo "Установите токен:"
    echo "export TELEGRAM_BOT_TOKEN='ваш_токен'"
    echo ""
    echo "Или создайте файл .env с содержимым:"
    echo "TELEGRAM_BOT_TOKEN=ваш_токен"
    echo ""
    exit 1
fi

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "Ошибка: Python3 не найден"
    echo "Установите Python 3.10+ с https://python.org"
    exit 1
fi

# Установка зависимостей
echo "Установка зависимостей..."
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Ошибка при установке зависимостей"
    exit 1
fi

echo ""
echo "Запуск бота..."
echo "Нажмите Ctrl+C для остановки"
echo ""

# Запуск бота
python3 main.py
