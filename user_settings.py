"""
Хранение настроек пользователей
"""
import json
import logging
from pathlib import Path
from typing import Optional

from config import SEARCH_CONFIG

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path(__file__).parent / "user_settings.json"

# Настройки по умолчанию
DEFAULT_SETTINGS = {
    "min_area": SEARCH_CONFIG["min_area"],
    "max_price": SEARCH_CONFIG["max_price"],
    "min_rooms": SEARCH_CONFIG["min_rooms"],
    "min_bathrooms": SEARCH_CONFIG["min_bathrooms"],
    "max_publication_age_days": SEARCH_CONFIG["max_publication_age_days"],
    "delivery_method": "telegram",  # telegram или email
    "email": "",
}


def load_settings() -> dict[int, dict]:
    """Загрузка всех настроек из файла"""
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.error(f"Ошибка загрузки настроек: {e}")
        return {}


def save_settings(settings: dict[int, dict]) -> None:
    """Сохранение всех настроек в файл"""
    try:
        data = {str(k): v for k, v in settings.items()}
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")


def get_user_settings(user_id: int) -> dict:
    """Получение настроек пользователя (с дефолтами)"""
    all_settings = load_settings()
    if user_id in all_settings:
        merged = DEFAULT_SETTINGS.copy()
        merged.update(all_settings[user_id])
        return merged
    return DEFAULT_SETTINGS.copy()


def set_user_settings(user_id: int, settings: dict) -> None:
    """Сохранение настроек пользователя"""
    all_settings = load_settings()
    all_settings[user_id] = settings
    save_settings(all_settings)
    logger.info(f"Настройки пользователя {user_id} сохранены")


def update_user_setting(user_id: int, key: str, value) -> None:
    """Обновление одного параметра"""
    settings = get_user_settings(user_id)
    settings[key] = value
    set_user_settings(user_id, settings)
