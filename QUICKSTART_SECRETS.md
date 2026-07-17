# Быстрый старт с секретами

## Вариант A: Простой (.env файл)

### 1. Создайте файл .env

```bash
# Скопируйте пример
cp .env.example .env
```

### 2. Заполните .env

```
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
BOT_NAME=КвартирыНск
```

### 3. Запустите

```bash
python main.py
```

---

## Вариант B: Зашифрованный (рекомендуется)

### 1. Установите cryptography

```bash
pip install cryptography
```

### 2. Создайте зашифрованные секреты

```bash
python secrets_crypto.py encrypt
```

Следуйте инструкциям:
- Введите пароль (запомните!)
- Введите токен бота
- Введите имя бота

### 3. Настройте пароль (выберите один способ)

**Способ 1: Переменная окружения (рекомендуется)**

```bash
# Windows PowerShell
$env:SECRETS_PASSWORD="ваш_пароль"

# Windows CMD
set SECRETS_PASSWORD=ваш_пароль

# Linux/Mac
export SECRETS_PASSWORD="ваш_пароль"
```

**Способ 2: Автоматический запрос**

Просто запустите бота — он запросит пароль.

### 4. Запустите бота

```bash
python main.py
```

---

## Полезные команды

```bash
# Проверить ключи
python secrets_crypto.py check

# Посмотреть секреты
python secrets_crypto.py decrypt

# Добавить ключ
python secrets_crypto.py set MY_KEY значение

# Получить ключ
python secrets_crypto.py get TELEGRAM_BOT_TOKEN
```

---

## Приоритет загрузки

1. Переменные окружения (самый высокий)
2. Зашифрованный файл `secrets.encrypted`
3. Файл `.env`

---

## Важно!

- Добавьте `.env` и `secrets.encrypted` в `.gitignore`
- Не публикуйте пароль и токен
- Используйте менеджер паролей для хранения пароля
