"""
Продакшен запуск: Flask dashboard + Telegram bot
"""
import os
import sys
import threading
import time
import subprocess
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent))


def run_flask():
    """Запуск Flask dashboard"""
    from miniapp.app import app
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Dashboard запущен на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False)


def run_bot():
    """Запуск Telegram бота"""
    # Небольшая задержка чтобы Flask успел стартовать
    time.sleep(3)
    print("🤖 Запуск Telegram бота...")
    try:
        from main import main
        main()
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")
        # Не останавливаем Flask если бот упал


if __name__ == "__main__":
    print("=" * 50)
    print("🏠 Apartment Bot - Production")
    print("=" * 50)

    # Проверяем токен
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("⚠️ TELEGRAM_BOT_TOKEN не установлен!")
        print("   Запускаем только дашборд...")
        run_flask()
    else:
        print(f"✅ Токен: {token[:10]}...{token[-5:]}")

        # Запускаем Flask в отдельном потоке
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()

        # Запускаем бота в основном потоке
        run_bot()
