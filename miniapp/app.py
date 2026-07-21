"""
Mini App дашборд для Telegram бота
Запуск: python miniapp/app.py
Доступ: http://localhost:5000
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, send_from_directory

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

app = Flask(__name__, template_folder="templates", static_folder="static")

STATS_FILE = Path(__file__).parent.parent / "bot_stats.json"


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


if __name__ == "__main__":
    print("🚀 Mini App дашборд запущен: http://localhost:5000")
    print("📱 В Telegram: откройте Mini App через кнопку Дашборд")
    app.run(host="0.0.0.0", port=5000, debug=False)
