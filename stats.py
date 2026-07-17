"""
Хранение статистики бота
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STATS_FILE = Path(__file__).parent / "bot_stats.json"


def load_stats() -> dict:
    """Загрузка статистики из файла"""
    if not STATS_FILE.exists():
        return _default_stats()
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки статистики: {e}")
        return _default_stats()


def save_stats(stats: dict) -> None:
    """Сохранение статистики в файл"""
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения статистики: {e}")


def _default_stats() -> dict:
    return {
        "start_time": datetime.now().isoformat(),
        "total_users": 0,
        "total_requests": 0,
        "total_tokens": 0,
        "total_found": 0,
        "users": {},  # {user_id: {"requests": N, "tokens": N, "found": N, "last_active": "..."}}
        "agencies": {  # по агентствам
            "cian": {"requests": 0, "found": 0},
            "avito": {"requests": 0, "found": 0},
            "n1": {"requests": 0, "found": 0},
            "domclick": {"requests": 0, "found": 0},
        },
        "daily": {},  # {"YYYY-MM-DD": {"users": N, "requests": N, "tokens": N, "found": N}}
    }


def track_request(user_id: int, username: str = "", tokens: int = 0, found: int = 0, agencies: dict = None) -> None:
    """Трекинг запроса"""
    stats = load_stats()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Используем username как ключ, fallback на ID
    key = f"@{username}" if username else str(user_id)
    
    # Общий счётчик
    stats["total_requests"] += 1
    stats["total_tokens"] += tokens
    stats["total_found"] += found
    
    # По пользователям
    if key not in stats["users"]:
        stats["users"][key] = {
            "requests": 0,
            "tokens": 0,
            "found": 0,
            "first_active": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
        }
    stats["users"][key]["requests"] += 1
    stats["users"][key]["tokens"] += tokens
    stats["users"][key]["found"] += found
    stats["users"][key]["last_active"] = datetime.now().isoformat()
    
    # По дням
    if today not in stats["daily"]:
        stats["daily"][today] = {"users": 0, "requests": 0, "tokens": 0, "found": 0}
    stats["daily"][today]["requests"] += 1
    stats["daily"][today]["tokens"] += tokens
    stats["daily"][today]["found"] += found
    
    # По агентствам
    if agencies:
        for agency, count in agencies.items():
            if agency in stats["agencies"]:
                stats["agencies"][agency]["found"] += count
    
    save_stats(stats)


def track_user(user_id: int, username: str = "") -> None:
    """Трекинг уникального пользователя"""
    stats = load_stats()
    key = f"@{username}" if username else str(user_id)
    
    if key not in stats["users"]:
        stats["total_users"] += 1
        stats["users"][key] = {
            "requests": 0,
            "tokens": 0,
            "found": 0,
            "first_active": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
        }
        save_stats(stats)


def _count_daily_users(stats: dict) -> None:
    """Подсчёт уникальных пользователей за каждый день"""
    for uid, data in stats["users"].items():
        if "last_active" in data:
            day = data["last_active"][:10]
            if day not in stats["daily"]:
                stats["daily"][day] = {"users": 0, "requests": 0, "tokens": 0, "found": 0}


def get_uptime() -> str:
    """Время работы бота"""
    stats = load_stats()
    start = datetime.fromisoformat(stats["start_time"])
    delta = datetime.now() - start
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    
    if days > 0:
        return f"{days}д {hours}ч {minutes}м"
    elif hours > 0:
        return f"{hours}ч {minutes}м"
    else:
        return f"{minutes}м"


def get_dashboard(period: str = "today") -> str:
    """Форматирование дашборда"""
    stats = load_stats()
    now = datetime.now()
    
    # Фильтрация по периоду
    if period == "today":
        start_date = now.strftime("%Y-%m-%d")
        label = "Сегодня"
    elif period == "week":
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        label = "За неделю"
    elif period == "month":
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        label = "За месяц"
    else:
        start_date = "0000-00-00"
        label = "За всё время"
    
    # Агрегация по дням
    total_requests = 0
    total_tokens = 0
    total_found = 0
    active_users = set()
    
    for day, data in stats.get("daily", {}).items():
        if day >= start_date:
            total_requests += data.get("requests", 0)
            total_tokens += data.get("tokens", 0)
            total_found += data.get("found", 0)
    
    # Уникальные пользователи за период
    for uid, data in stats.get("users", {}).items():
        last = data.get("last_active", "")[:10]
        if last >= start_date:
            active_users.add(uid)
    
    # Топ-3 активных пользователей
    top_users = []
    for uid, data in stats.get("users", {}).items():
        last = data.get("last_active", "")[:10]
        if last >= start_date:
            top_users.append((uid, data))
    top_users.sort(key=lambda x: x[1].get("requests", 0), reverse=True)
    top_3 = top_users[:3]
    
    # Статистика по агентствам
    agencies = stats.get("agencies", {})
    
    # Формирование отчёта
    report = (
        f"📊 ДАШБОРД — {label}\n"
        f"{'=' * 30}\n\n"
        f"⏱ Время работы: {get_uptime()}\n"
        f"👥 Пользователей: {len(active_users)}\n"
        f"🔍 Запросов: {total_requests}\n"
        f"🔤 Токенов: {total_tokens}\n"
        f"🏠 Найдено квартир: {total_found}\n\n"
        f"{'=' * 30}\n"
        f"📈 ПО АГЕНТСТВАМ\n"
        f"{'-' * 30}\n"
    )
    
    agency_names = {"cian": "Циан", "avito": "Авито", "n1": "N1.RU", "domclick": "Домклик"}
    for key, name in agency_names.items():
        data = agencies.get(key, {"requests": 0, "found": 0})
        report += f"• {name}: найдено {data.get('found', 0)}\n"
    
    report += f"\n{'=' * 30}\n"
    report += f"🏆 ТОП-3 АКТИВНЫХ ПОЛЬЗОВАТЕЛЕЙ\n"
    report += f"{'-' * 30}\n"
    
    for i, (key, data) in enumerate(top_3, 1):
        report += (
            f"{i}. {key}\n"
            f"   Запросов: {data.get('requests', 0)}\n"
            f"   Токенов: {data.get('tokens', 0)}\n"
            f"   Найдено: {data.get('found', 0)}\n"
        )
    
    if not top_3:
        report += "Нет данных\n"
    
    return report
