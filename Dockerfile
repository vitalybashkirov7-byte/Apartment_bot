FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Создание директории для логов
RUN mkdir -p /app/logs

# Переменная окружения для токена
ENV TELEGRAM_BOT_TOKEN=""

# Запуск бота
CMD ["python", "main.py"]
