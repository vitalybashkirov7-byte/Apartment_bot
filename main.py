"""
Точка входа для Telegram-бота поиска квартир в Новосибирске
"""
import os
import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from config import TELEGRAM_BOT_TOKEN, LOG_FILE, LOG_LEVEL, MAX_LOG_SIZE_MB, HTTP_PROXY


# === Автоперезагрузка при изменении .py файлов ===
_WATCHED_FILES: dict[str, float] = {}
_WATCH_DIR = os.path.dirname(os.path.abspath(__file__))


def _collect_py_mtimes() -> dict[str, float]:
    """Собрать mtime всех .py файлов в проекте"""
    mtimes = {}
    for root, _dirs, files in os.walk(_WATCH_DIR):
        # Пропускаем __pycache__, .git, venv
        if any(skip in root for skip in ("__pycache__", ".git", "venv", ".venv", "node_modules")):
            continue
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                try:
                    mtimes[path] = os.path.getmtime(path)
                except OSError:
                    pass
    return mtimes


def _watcher_loop():
    """Фоновый поток: проверяет mtime .py файлов, перезапускает процесс при изменении"""
    global _WATCHED_FILES
    _WATCHED_FILES = _collect_py_mtimes()
    logger = logging.getLogger("watcher")
    logger.info(f"Auto-reload: отслеживаю {len(_WATCHED_FILES)} .py файлов")

    while True:
        time.sleep(2)
        current = _collect_py_mtimes()
        changed = [p for p, t in current.items() if _WATCHED_FILES.get(p, 0) < t]
        if changed:
            logger.info(f"Auto-reload: изменены файлы: {[os.path.basename(p) for p in changed]}")
            logger.info("Auto-reload: перезапуск процесса...")
            # Очистка .pyc перед перезапуском
            for root, dirs, _ in os.walk(_WATCH_DIR):
                if "__pycache__" in root:
                    import shutil
                    shutil.rmtree(root, ignore_errors=True)
            # Перезапуск процесса
            os.execv(sys.executable, [sys.executable] + sys.argv)


def start_auto_reload():
    """Запуск auto-reload в фоновом потоке"""
    t = threading.Thread(target=_watcher_loop, daemon=True, name="auto-reload")
    t.start()
from bot import create_bot


def setup_logging():
    """Настройка логирования с ротацией файлов"""
    # Максимальный размер в байтах
    max_bytes = MAX_LOG_SIZE_MB * 1024 * 1024
    
    # Создаём ротирующий обработчик
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=max_bytes,
        backupCount=5,  # Храним 5 старых файлов (.1, .2, ...)
        encoding="utf-8"
    )
    
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            file_handler,
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    # Уменьшаем шум от библиотек
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.DEBUG)
    logging.getLogger("telegram.ext").setLevel(logging.DEBUG)


def main():
    """Основная функция запуска бота"""
    # Настройка логирования
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("Запуск бота поиска квартир в Новосибирске")
    logger.info(f"Максимальный размер лога: {MAX_LOG_SIZE_MB} МБ")

    # Auto-reload: перезапуск при изменении .py файлов
    start_auto_reload()
    
    # Проверка токена
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Не установлен TELEGRAM_BOT_TOKEN")
        print("❌ Ошибка: Установите переменную окружения TELEGRAM_BOT_TOKEN")
        sys.exit(1)
    
    # Создание и запуск бота с поддержкой прокси
    try:
        # Прокси для Telegram API (только из config, НЕ из env)
        PROXY = HTTP_PROXY

        # Увеличиваем дефолтный timeout httpx (5с → 60с)
        os.environ["HTTPX_DEFAULT_TIMEOUT"] = "60"

        # Создаём бота с учётом прокси
        application = create_bot(proxy=PROXY)
        
        logger.info("Бот запущен и готов к работе")
        print("✅ Бот запущен! Нажмите Ctrl+C для остановки.")
        if PROXY:
            print(f"🔒 Используется прокси: {PROXY}")
        application.run_polling(
            allowed_updates=["message", "callback_query"],
            drop_pending_updates=True,
            timeout=1,
        )
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
        print("\n⏹ Бот остановлен.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()