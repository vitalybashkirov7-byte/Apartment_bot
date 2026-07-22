"""
Mini App дашборд для Telegram бота
Запуск: python miniapp/app.py
Доступ: http://localhost:5000
"""
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, jsonify, render_template, request, redirect, url_for

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import TELEGRAM_BOT_TOKEN

app = Flask(__name__, template_folder="templates", static_folder="static")

STATS_FILE = Path(__file__).parent.parent / "bot_stats.json"


# ============================================
# Telegram WebApp Authentication
# ============================================

def validate_telegram_init_data(init_data: str) -> dict | None:
    """Валидация initData от Telegram WebApp через HMAC-SHA256.

    Returns:
        dict с данными пользователя или None если валидация не прошла
    """
    try:
        # Парсим initData в словарь
        data = {}
        for item in init_data.split("&"):
            if "=" in item:
                key, value = item.split("=", 1)
                data[key] = unquote(value)

        # Извлекаем hash и удаляем его из данных
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None

        # Создаём строку для проверки (ключи в алфавитном порядке, hash исключён)
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(data.items())
        )

        # HMAC-SHA256 с bot_token как секретом
        secret_key = hmac.new(
            b"WebAppData",
            TELEGRAM_BOT_TOKEN.encode(),
            hashlib.sha256,
        ).digest()

        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        # Сравниваем хеши
        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        # Проверяем时效 (auth_date не старше 24 часов)
        auth_date = int(data.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            return None

        return data

    except Exception:
        return None


def require_auth(f):
    """Декоратор: проверка авторизации Telegram WebApp"""
    @wraps(f)
    def decorated(*args, **kwargs):
        init_data = request.headers.get("X-Telegram-Init-Data") or request.args.get("init_data")
        if not init_data:
            return jsonify({"error": "Unauthorized"}), 401

        user_data = validate_telegram_init_data(init_data)
        if not user_data:
            return jsonify({"error": "Invalid authentication"}), 401

        request.telegram_user = user_data
        return f(*args, **kwargs)
    return decorated


def load_stats() -> dict:
    """Загрузка статистики"""
    if not STATS_FILE.exists():
        return {
            "start_time": datetime.now().isoformat(),
            "total_users": 0,
            "total_requests": 0,
            "total_found": 0,
            "users": {},
            "agencies": {
                "cian": {"found": 0},
                "avito": {"found": 0},
                "n1": {"found": 0},
                "domclick": {"found": 0},
            },
            "daily": {},
        }
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.route("/")
def index():
    """Главная страница дашборда"""
    return render_template("dashboard.html")


@app.route("/api/stats")
@require_auth
def api_stats():
    """API: получение статистики"""
    stats = load_stats()
    now = datetime.now()

    # Агрегация за сегодня
    today_str = now.strftime("%Y-%m-%d")
    today_data = stats.get("daily", {}).get(today_str, {"requests": 0, "found": 0})

    # Агрегация за неделю
    week_requests = 0
    week_found = 0
    for day, data in stats.get("daily", {}).items():
        if day >= (now - timedelta(days=7)).strftime("%Y-%m-%d"):
            week_requests += data.get("requests", 0)
            week_found += data.get("found", 0)

    # Агрегация за месяц
    month_requests = 0
    month_found = 0
    for day, data in stats.get("daily", {}).items():
        if day >= (now - timedelta(days=30)).strftime("%Y-%m-%d"):
            month_requests += data.get("requests", 0)
            month_found += data.get("found", 0)

    # Uptime
    start_time = datetime.fromisoformat(stats.get("start_time", now.isoformat()))
    uptime = now - start_time
    uptime_hours = uptime.total_seconds() / 3600

    # Топ пользователей
    top_users = []
    for uid, data in stats.get("users", {}).items():
        top_users.append({"name": uid, "requests": data.get("requests", 0), "found": data.get("found", 0)})
    top_users.sort(key=lambda x: x["requests"], reverse=True)

    # По источникам
    agencies = stats.get("agencies", {})

    return jsonify({
        "today": {
            "requests": today_data.get("requests", 0),
            "found": today_data.get("found", 0),
        },
        "week": {
            "requests": week_requests,
            "found": week_found,
        },
        "month": {
            "requests": month_requests,
            "found": month_found,
        },
        "total": {
            "users": stats.get("total_users", 0),
            "requests": stats.get("total_requests", 0),
            "found": stats.get("total_found", 0),
        },
        "uptime_hours": round(uptime_hours, 1),
        "agencies": {
            "cian": agencies.get("cian", {}).get("found", 0),
            "avito": agencies.get("avito", {}).get("found", 0),
            "n1": agencies.get("n1", {}).get("found", 0),
            "domclick": agencies.get("domclick", {}).get("found", 0),
        },
        "top_users": top_users[:10],
        "generated_at": now.isoformat(),
    })


@app.route("/api/user")
@require_auth
def api_user():
    """API: информация о текущем пользователе"""
    user = request.telegram_user
    return jsonify({
        "id": user.get("id"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "username": user.get("username"),
        "language_code": user.get("language_code"),
        "is_premium": user.get("is_premium", False),
    })


if __name__ == "__main__":
    print("🚀 Mini App дашборд запущен: http://localhost:5000")
    print("📱 В Telegram: откройте Mini App через кнопку Дашборд")
    app.run(host="0.0.0.0", port=5000, debug=False)
