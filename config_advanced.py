"""
Дополнительные настройки для прокси и расширенного парсинга
"""
import os

# Прокси-серверы (раскомментируйте и настройте при необходимости)
PROXY_CONFIG = {
    # Пример: "http://user:password@proxy:port"
    "http": os.getenv("HTTP_PROXY", None),
    "https": os.getenv("HTTPS_PROXY", None),
}

# Список прокси для ротации (опционально)
PROXY_LIST = [
    # "http://proxy1:port",
    # "http://proxy2:port",
    # "http://proxy3:port",
]

# Настройки Selenium
SELENIUM_CONFIG = {
    "headless": True,
    "page_load_timeout": 30,
    "implicit_wait": 10,
}

# RSS-ленты (если доступны)
RSS_FEEDS = {
    "cian": "https://www.cian.ru/export/rss/cat.php?city=2&deal_type=sale&offer_type=flat",
    # Авито не предоставляет RSS
    "n1": "https://n1.ru/realty/novosibirsk/rss/",
}

# API ключи (если доступны)
API_KEYS = {
    "cian": os.getenv("CIAN_API_KEY", None),
    # Авито API требует отдельной регистрации
}

# Настройки антибот-защиты
ANTI_DETECTION = {
    "random_delay": True,  # Случайная задержка между запросами
    "min_delay": 1,
    "max_delay": 5,
    "rotate_user_agents": True,  # Ротация User-Agent
}

# Список User-Agent для ротации
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]
