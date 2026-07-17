# Безопасное хранение секретов для Telegram-бота

## Зачем это нужно?

Хранить секреты (токены, пароли) в коде — плохая практика. Если код попадёт в Git или к нему получит доступ посторонний, ваши ключи будут скомпрометированы.

## Варианты хранения секретов

### Вариант 1: Переменные окружения (рекомендуется)

```bash
# Windows (PowerShell)
$env:TELEGRAM_BOT_TOKEN="ваш_токен"

# Linux/Mac
export TELEGRAM_BOT_TOKEN="ваш_токен"
```

### Вариант 2: Файл .env

Создайте файл `.env` в корне проекта:

```
TELEGRAM_BOT_TOKEN=ваш_токен
BOT_NAME=МойБот
```

### Вариант 3: Зашифрованный файл (наиболее безопасно)

## Пошаговая инструкция

### Шаг 1: Установите зависимости

```bash
pip install cryptography
```

### Шаг 2: Создайте зашифрованные секреты

```bash
python secrets_crypto.py encrypt
```

Бот попросит ввести:
1. Пароль для шифрования (запомните его!)
2. Telegram Bot Token
3. Имя бота (опционально)
4. Прокси (опционально)

### Шаг 3: Настройте пароль

#### Способ A: Через переменную окружения

```bash
# Windows
$env:SECRETS_PASSWORD="ваш_пароль"

# Linux/Mac
export SECRETS_PASSWORD="ваш_пароль"
```

#### Способ B: При запуске

При запуске бота будет запрошен пароль.

### Шаг 4: Запустите бота

```bash
python main.py
```

## Команды управления секретами

### Проверить наличие ключей

```bash
python secrets_crypto.py check
```

### Посмотреть расшифрованные секреты

```bash
python secrets_crypto.py decrypt
```

### Добавить/изменить ключ

```bash
python secrets_crypto.py set NEW_KEY значение
```

### Получить значение ключа

```bash
python secrets_crypto.py get TELEGRAM_BOT_TOKEN
```

## Приоритет загрузки секретов

Бот загружает секреты в следующем порядке:

1. **Переменные окружения** (наивысший приоритет)
2. **Зашифрованный файл** `secrets.encrypted`
3. **Файл** `.env`

Это значит, что переменная окружения перезапишет значение из файла.

## Безопасность

### Что делать

- ✅ Используйте сильный пароль для шифрования
- ✅ Храните пароль в безопасном месте (менеджер паролей)
- ✅ Добавьте `.env` и `secrets.encrypted` в `.gitignore`
- ✅ Используйте переменные окружения на сервере

### Чего не делать

- ❌ Не коммитьте `.env` или `secrets.encrypted` в Git
- ❌ Не храните пароль в коде
- ❌ Не передавайте пароль по незащищённым каналам
- ❌ Не используйте один пароль для разных проектов

## Удаление секретов

Если нужно удалить зашифрованный файл:

```bash
# Windows
del secrets.encrypted

# Linux/Mac
rm secrets.encrypted
```

## Восстановление секретов

Если вы забыли пароль:

1. Если есть резервная копия `.env` — используйте её
2. Если есть переменная окружения — она имеет приоритет
3. Если ничего нет — потребуется новый токен от @BotFather

## Примеры использования

### Автоматическая загрузка в скрипте

```python
from config import TELEGRAM_BOT_TOKEN, BOT_NAME

# Секреты уже загружены при импорте config
print(f"Бот: {BOT_NAME}")
```

### Ручная загрузка

```python
from secrets_crypto import CryptoSecretsManager

manager = CryptoSecretsManager(password="мой_пароль")
token = manager.get("TELEGRAM_BOT_TOKEN")
```

## Частые вопросы

### Q: Я потерял пароль. Что делать?

A: Создайте новый токен у @BotFather и заново зашифруйте секреты.

### Q: Можно ли использовать без пароля?

A: Да, используйте переменные окружения или файл `.env`.

### Q: Как безопасно хранить пароль?

A: Используйте менеджер паролей (1Password, Bitwarden, KeePass).

### Q: Файл `secrets.encrypted` повреждён. Что делать?

A: Удалите его и создайте заново через `python secrets_crypto.py encrypt`.

## Дополнительные ресурсы

- [OWASP: Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
- [Python cryptography docs](https://cryptography.io/)
- [dotenv specification](https://github.com/motdotla/dotenv)
