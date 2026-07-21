"""
Конфигурация Telegram-бота для поиска квартир в Новосибирске

Приоритет загрузки секретов:
1. Переменные окружения (наивысший)
2. Зашифрованный файл secrets.encrypted
3. Файл .env
"""
import os
import sys
from pathlib import Path
from typing import Optional

# Добавляем текущую директорию в путь для импорта модулей
sys.path.insert(0, str(Path(__file__).parent))


def load_dotenv(env_file: Path = None) -> None:
    """Загрузка переменных из .env файла"""
    if env_file is None:
        env_file = Path(__file__).parent / ".env"
    
    if not env_file.exists():
        return
    
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                
                # Не перезаписываем существующие переменные окружения
                if key not in os.environ:
                    os.environ[key] = value


def load_from_secrets_file(password: Optional[str] = None) -> None:
    """Загрузка секретов из зашифрованного файла"""
    secrets_file = Path(__file__).parent / "secrets.encrypted"
    
    if not secrets_file.exists():
        return
    
    try:
        # Пробуем импортировать менеджер секретов
        from secrets_crypto import CryptoSecretsManager
        
        # Если пароль задан в окружении, используем его
        env_password = os.getenv("SECRETS_PASSWORD")
        if env_password or password:
            manager = CryptoSecretsManager(password=env_password or password)
            secrets = manager.decrypt()
            
            # Загружаем в переменные окружения
            for key, value in secrets.items():
                if key not in os.environ:
                    os.environ[key] = value
    
    except ImportError:
        # Если cryptography не установлена, пробуем простой вариант
        try:
            from secrets_manager import SecretsManager
            
            password = os.getenv("SECRETS_PASSWORD") or password
            if password:
                manager = SecretsManager(password=password)
                secrets = manager.decrypt()
                
                for key, value in secrets.items():
                    if key not in os.environ:
                        os.environ[key] = value
        except Exception:
            pass
    except Exception:
        pass


def get_secret(key: str, default: str = "", required: bool = False) -> str:
    """
    Получение секрета с приоритетом загрузки
    
    Args:
        key: Имя ключа
        default: Значение по умолчанию
        required: Если True, выбрасывает ошибку при отсутствии
        
    Returns:
        Значение секрета
    """
    value = os.getenv(key, default)
    
    if required and not value:
        raise ValueError(
            f"❌ Секрет {key} не найден!\n\n"
            "Установите его одним из способов:\n"
            "1. Переменная окружения: export {key}='значение'\n"
            "2. Файл .env: {key}=значение\n"
            "3. Зашифрованный файл: python secrets_crypto.py set {key} значение"
        )
    
    return value


# ============================================
# ЗАГРУЗКА СЕКРЕТОВ
# ============================================

# 1. Загружаем .env файл (если есть)
load_dotenv()

# 2. Загружаем зашифрованный файл (если есть)
load_from_secrets_file()

# ============================================
# ОСНОВНЫЕ НАСТРОЙКИ
# ============================================

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN", required=True)

# Имя бота (для логов и отображения)
BOT_NAME = get_secret("BOT_NAME", "ApartmentBot NS")

# Уровень логирования
LOG_LEVEL = get_secret("LOG_LEVEL", "INFO")

# Фото Новосибирска при старте
START_PHOTO_URL = get_secret(
    "START_PHOTO_URL",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8e/Novosibirsk_Opera_Theater.jpg/1280px-Novosibirsk_Opera_Theater.jpg"
)

# Telegram ID разработчика (для обратной связи)
DEV_CHAT_ID = int(get_secret("DEV_CHAT_ID", "1515904523"))

# Лимиты пользователей
RATE_LIMIT_PER_MINUTE = int(get_secret("RATE_LIMIT_PER_MINUTE", "5"))
DAILY_LIMIT_PER_USER = int(get_secret("DAILY_LIMIT_PER_USER", "50"))

# Режим отладки
DEBUG_MODE = get_secret("DEBUG_MODE", "false").lower() == "true"

# URL Mini App дашборда (для Telegram WebApp)
MINIAPP_URL = get_secret("MINIAPP_URL", "http://localhost:5000")

# ============================================
# ПРОКСИ (опционально)
# ============================================

# USE_PROXY=true — включить прокси для Telegram API
# Прокси передаётся ЯВНО через HTTPXRequest, НЕ через env-переменные.
# Env-переменные прокси ВСЕГДА очищаются — иначе ломают Playwright и UC парсеры.
USE_PROXY = get_secret("USE_PROXY", "false").lower() == "true"

if USE_PROXY:
    HTTP_PROXY = get_secret("HTTP_PROXY")
    HTTPS_PROXY = get_secret("HTTPS_PROXY")
else:
    HTTP_PROXY = ""
    HTTPS_PROXY = ""

# Всегда чистим env — парсеры не должны видеть прокси
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)

PROXY_CONFIG = {}
if HTTP_PROXY:
    PROXY_CONFIG["http"] = HTTP_PROXY
if HTTPS_PROXY:
    PROXY_CONFIG["https"] = HTTPS_PROXY

# ============================================
# ПАРАМЕТРЫ ПОИСКА КВАРТИР
# ============================================

SEARCH_CONFIG = {
    "city": "Новосибирск",
    "min_area": int(get_secret("MIN_AREA", "90")),  # мин. площадь в м²
    "max_price": int(get_secret("MAX_PRICE", "17000000")),  # макс. цена в рублях
    "min_rooms": int(get_secret("MIN_ROOMS", "3")),  # мин. количество комнат
    "min_bathrooms": int(get_secret("MIN_BATHROOMS", "2")),  # мин. количество санузлов
    "min_floor": 2,  # не первый этаж
    "max_year": 1985,  # год постройки не старше 1985
    "max_publication_age_days": int(get_secret("MAX_PUBLICATION_AGE_DAYS", "3")),  # макс. срок давности публикации (дни)
}

# ============================================
# ИСТОЧНИКИ ДАННЫХ
# ============================================

SOURCES = {
    "cian": "https://www.cian.ru",
    "avito": "https://www.avito.ru",
    "n1": "https://n1.ru",
    "domclick": "https://domclick.ru",
}

# ============================================
# НАСТРОЙКИ СЕТЕВЫХ ЗАПРОСОВ
# ============================================

# Время кеширования в секундах (1 час)
CACHE_TTL = int(get_secret("CACHE_TTL", "3600"))

# Задержка между запросами к сайтам (в секундах)
REQUEST_DELAY = int(get_secret("REQUEST_DELAY", "2"))

# Таймаут запроса к сайту (в секундах)
REQUEST_TIMEOUT = int(get_secret("REQUEST_TIMEOUT", "30"))

# User-Agent для имитации браузера
USER_AGENT = get_secret(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ============================================
# ФИЛЬТРЫ "ПРИЛИЧНЫХ" КВАРТИР
# ============================================

DECENT_FILTERS = {
    "not_first_floor": True,
    "not_last_floor": True,
    "has_balcony": True,
    "min_condition": "хорошее",  # хорошее или евроремонт
}

# ============================================
# ЛОГИРОВАНИЕ
# ============================================

LOG_FILE = get_secret("LOG_FILE", "bot.log")
MAX_LOG_SIZE_MB = int(get_secret("MAX_LOG_SIZE_MB", "50"))

# ============================================
# ПРОВЕРКА КОНФИГУРАЦИИ
# ============================================

def validate_config() -> None:
    """Проверка корректности конфигурации"""
    errors = []
    
    # Проверяем обязательные настройки
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN не задан")
    
    if SEARCH_CONFIG["min_area"] <= 0:
        errors.append("MIN_AREA должен быть больше 0")
    
    if SEARCH_CONFIG["max_price"] <= 0:
        errors.append("MAX_PRICE должен быть больше 0")
    
    if errors:
        print("❌ Ошибки конфигурации:")
        for error in errors:
            print(f"  • {error}")
        sys.exit(1)


# Выполняем проверку при импорте
if __name__ != "__main__":
    # Не проверяем при прямом запуске файла
    pass
