# Пошаговая инструкция по настройке бота

## Шаг 1: Установка Python

### Windows

1. Перейдите на https://python.org/downloads
2. Скачайте последнюю версию Python 3.10+
3. Запустите установщик
4. **Обязательно поставьте галочку "Add Python to PATH"**
5. Нажмите "Install Now"

### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

### macOS

```bash
brew install python@3.11
```

## Шаг 2: Создание бота в Telegram

1. Откройте Telegram и найдите [@BotFather](https://t.me/BotFather)
2. Отправьте команду `/newbot`
3. Введите имя бота (например, "Поиск квартир Новосибирск")
4. Введите username бота (например, "apartments_nsk_bot")
5. Скопируйте полученный токен

## Шаг 3: Клонирование проекта

```bash
# Клонируйте репозиторий
git clone https://github.com/your-repo/apartment_bot.git

# Перейдите в директорию
cd apartment_bot
```

## Шаг 4: Установка зависимостей

### Windows

```bash
pip install -r requirements.txt
```

### Linux/macOS

```bash
pip3 install -r requirements.txt
```

## Шаг 5: Настройка переменных окружения

Скопируйте `.env.example` в `.env` и заполните:

```env
# Обязательно
TELEGRAM_BOT_TOKEN=ваш_токен
DEV_CHAT_ID=ваш_telegram_id

# Параметры поиска (по умолчанию)
MIN_AREA=90
MAX_PRICE=17000000
MIN_ROOMS=3
MIN_BATHROOMS=2

# Лимиты
RATE_LIMIT_PER_MINUTE=5
DAILY_LIMIT_PER_USER=50

# Логирование (INFO или DEBUG для дашборда)
LOG_LEVEL=INFO
```

### Получение Telegram ID

1. Найдите бота [@userinfobot](https://t.me/userinfobot)
2. Отправьте `/start`
3. Скопируйте ваш ID

## Шаг 6: Запуск бота

### Windows

```bash
python main.py
```

### Linux/macOS

```bash
python3 main.py
```

### Использование скрипта запуска

Windows:
```bash
start.bat
```

Linux/macOS:
```bash
chmod +x start.sh
./start.sh
```

## Шаг 7: Проверка работы

1. Откройте Telegram
2. Найдите вашего бота по username
3. Отправьте команду `/start`
4. Вы увидите фото Новосибирского Оперного театра и меню
5. Нажмите "🔍 Поиск квартир"
6. Дождитесь результатов с прогресс-индикатором
7. Попробуйте "⚙️ Настройки" для изменения параметров
8. Попробуйте "📩 Подписаться/Отписаться" для оформления подписки

## Дополнительные настройки

### Настройка прокси

Если сайты блокируют парсинг, настройте прокси:

1. Отредактируйте файл `config_advanced.py`
2. Добавьте прокси-серверы:

```python
PROXY_CONFIG = {
    "http": "http://user:password@proxy:port",
    "https": "http://user:password@proxy:port",
}
```

### Настройка Selenium

Для более надёжного парсинга установите Selenium:

```bash
pip install selenium webdriver-manager
```

Затем используйте `parser_selenium.py` вместо `parser.py`.

## Решение проблем

### Проблема: Python не найден

**Решение:** Установите Python и добавьте его в PATH

### Проблема: Модули не найдены

**Решение:** Установите зависимости:
```bash
pip install -r requirements.txt
```

Для обхода блокировок также:
```bash
pip install curl_cffi
```

### Проблема: Бот не отвечает

**Решение:** Проверьте:
1. Токен бота правильный
2. Бот запущен
3. Есть подключение к интернету
4. Нет другого экземпляра бота (проверьте `bot.log` на ошибки Conflict)

### Проблема: Нет результатов поиска

**Решение:**
1. Бот показывает причину для каждого сайта в чате
2. Проверьте `bot.log` для деталей
3. Возможные причины:
   - HTTP 429 — блокировка (подождите или добавьте прокси)
   - HTTP 401 — требуется авторизация (Домклик)
   - 0 объявлений — селекторы устарели
4. Настройте прокси в `.env`:
   ```
   HTTP_PROXY=http://user:pass@proxy:port
   HTTPS_PROXY=http://user:pass@proxy:port
   ```

### Проблема: Квартиры найдены, но не показаны

**Решение:** Бот объясняет причину:
```
⚠️ Найденные квартиры не прошли фильтр:
  • ул. Примерная, 5 — нет балкона, состояние: среднее
```

## Полезные команды

```bash
# Просмотр логов
tail -f bot.log

# Проверка установленных пакетов
pip list

# Обновление зависимостей
pip install --upgrade -r requirements.txt

# Запуск тестов
pytest test_parser.py -v
```

## Контакты

Если возникли вопросы, создайте issue в репозитории или напишите на email.
