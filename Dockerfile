FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей для Playwright и Chrome
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    chromium \
    chromium-driver \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgdk-pixbuf2.0-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка Playwright браузеров
RUN playwright install chromium

# Копирование кода
COPY . .

# Создание директорий
RUN mkdir -p /app/logs

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV TELEGRAM_BOT_TOKEN=""
ENV MINIAPP_URL=""
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Порты
EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/stats')" || exit 1

# Запуск: Flask dashboard + Telegram bot
CMD ["python", "run_prod.py"]
