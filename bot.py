"""
Telegram-бот для поиска квартир в Новосибирске
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta, time
from typing import Optional

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from pathlib import Path
from config import TELEGRAM_BOT_TOKEN, START_PHOTO_URL, SEARCH_CONFIG, USER_AGENT, DEBUG_MODE, RATE_LIMIT_PER_MINUTE, DAILY_LIMIT_PER_USER, LOG_LEVEL
from parser import Apartment, get_last_apartments, search_apartments
from user_settings import get_user_settings, update_user_setting
from stats import track_request, track_user, get_dashboard

logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ApartmentBot:
    """Telegram-бот для поиска квартир"""
    
    def __init__(self):
        self.subscribed_users: set[int] = set()
        self.last_search_results: list[Apartment] = []
        self.last_search_time: Optional[datetime] = None
        self.feedback_users: set[int] = set()
        self.user_activity: dict[int, datetime] = {}
        self.user_states: dict[int, str] = {}
        self.user_data: dict[int, dict] = {}
        self.user_requests_minute: dict[int, list[datetime]] = {}
        self.user_requests_day: dict[int, dict] = {}
        self.user_tokens_day: dict[int, dict] = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start"""
        user = update.effective_user
        user_id = user.id
        self.update_activity(user_id)
        
        if DEBUG_MODE:
            track_user(user_id, user.username or "")
        
        welcome_message = (
            f"👋 Привет, {user.first_name}!\n\n"
            "Я помогу найти квартиры в Новосибирске по вашим параметрам.\n\n"
            f"{self._format_search_params(user_id)}"
        )
        
        if DEBUG_MODE:
            stats = self.format_stats(user_id)
            welcome_message += f"\n\n{stats}"
        
        keyboard = [
            [InlineKeyboardButton("🔍 Поиск квартир", callback_data="search")],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
            [InlineKeyboardButton("📋 Последние объявления", callback_data="last")],
            [InlineKeyboardButton("📩 Подписаться/Отписаться", callback_data="toggle_subscribe")],
            [InlineKeyboardButton("💬 Обратная связь", callback_data="feedback")],
            [InlineKeyboardButton("🚪 Exit", callback_data="exit_bot")],
        ]
        
        if LOG_LEVEL.upper() == "DEBUG":
            keyboard.insert(0, [InlineKeyboardButton("🧪 Тест парсеров", callback_data="test_parsers")])
            keyboard.insert(0, [InlineKeyboardButton("📊 Дашборд", callback_data="dashboard")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        local_photo = Path(__file__).parent / "start_photo.jpg"
        try:
            if local_photo.exists():
                with open(local_photo, "rb") as photo:
                    await update.message.reply_photo(photo=photo, caption=welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_photo(photo=START_PHOTO_URL, caption=welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        
        logger.info(f"Пользователь @{update.effective_user.username or 'unknown'} запустил бота")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /help"""
        help_message = (
            "📖 Помощь по боту\n\n"
            "🔍 Поиск квартир:\n"
            "• /search - поиск актуальных объявлений\n"
            "• Бот ищет квартиры на Циан, Авито, N1.RU и Домклик\n"
            "• Фильтрует только приличные варианты\n\n"
            "📋 Просмотр результатов:\n"
            "• /last - показать 5 последних найденных квартир\n"
            "• Результаты кешируются на 1 час\n\n"
            "📩 Подписка:\n"
            "• /subscribe - подписка на ежедневную рассылку\n"
            "• /unsubscribe - отписка от рассылки\n\n"
            "ℹ️ Параметры поиска:\n"
            "• Город: Новосибирск\n"
            "• Площадь: от 100 м²\n"
            "• Комнат: 3 или более\n"
            "• Санузлов: 2\n"
            "• Цена: до 17 000 000 ₽\n"
            "• Этаж: не первый и не последний\n"
            "• Есть балкон/лоджия\n"
            "• Хорошее состояние или евроремонт\n"
            "• Год постройки не старше 1990"
        )
        await update.message.reply_text(help_message)
    
    async def _do_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Внутренний метод поиска"""
        self.update_activity(user_id)
        self.track_request(user_id)

        if not self.check_rate_limit(user_id):
            await update.effective_message.reply_text("⚠️ Превышен лимит запросов в минуту. Пожалуйста, подождите.")
            return

        if not self.check_daily_limit(user_id):
            await update.effective_message.reply_text("⚠️ Превышен дневной лимит запросов. Попробуйте завтра.")
            return

        settings = get_user_settings(user_id)
        max_age_days = settings.get("max_publication_age_days", 3)

        params = self._format_search_params(user_id)
        status_msg = await update.effective_message.reply_text(f"🔍 Начинаю поиск...\n\n{params}", parse_mode=ParseMode.HTML)

        try:
            apartments = []
            sources = [("Циан", "cian"), ("Авито", "avito"), ("N1.RU", "n1"), ("Домклик", "domclick")]

            async with aiohttp.ClientSession(headers={"User-Agent": SEARCH_CONFIG.get("user_agent", "Mozilla/5.0")}) as session:
                from parser import parse_cian_playwright, parse_avito_playwright, parse_n1_playwright, parse_domclick_playwright
                results = []
                log_lines = []

                for name, _ in sources:
                    try:
                        await status_msg.edit_text(f"🔍 Ищу квартиры...\n\n⏳ {name}...")
                    except Exception:
                        pass

                    try:
                        if name == "Циан":
                            result = await parse_cian_playwright()
                        elif name == "Авито":
                            result = await parse_avito_playwright()
                        elif name == "N1.RU":
                            result = await parse_n1_playwright()
                        elif name == "Домклик":
                            result = await parse_domclick_playwright()
                        else:
                            result = []

                        count = len(result) if isinstance(result, list) else 0
                        log_lines.append(f"✅ {name}: {count} объявлений")
                        results.append(result)
                    except Exception as e:
                        error_text = str(e)
                        log_lines.append(f"❌ {name}: {error_text[:80]}")
                        results.append([])

                    await asyncio.sleep(1)

            agency_counts = {"cian": 0, "avito": 0, "n1": 0, "domclick": 0}
            for result in results:
                if isinstance(result, list):
                    apartments.extend(result)
                    for apt in result:
                        if apt.source in agency_counts:
                            agency_counts[apt.source] += 1

            from parser import is_decent_apartment
            decent = [apt for apt in apartments if is_decent_apartment(apt, max_age_days)]
            decent.sort(key=lambda x: x.price)

            if DEBUG_MODE:
                tokens_used = self.estimate_tokens(str(decent))
                track_request(user_id, username=update.effective_user.username or "", tokens=tokens_used, found=len(decent), agencies=agency_counts)

            self.last_search_results = decent
            self.last_search_time = datetime.now()

            search_log = "📋 Лог поиска:\n" + "\n".join(log_lines)
            search_log += f"\n\n📊 Итого: {len(apartments)} найдено, {len(decent)} приличных"

            if max_age_days > 0:
                search_log += f"\n📅 Срок давности: до {max_age_days} дн."

            await status_msg.edit_text(search_log)

            if not decent:
                await update.effective_message.reply_text("😔 К сожалению, подходящих квартир не найдено. Попробуйте позже или измените параметры поиска.")
                keyboard = [
                    [InlineKeyboardButton("🔍 Поиск квартир", callback_data="search")],
                    [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
                    [InlineKeyboardButton("🏠 Меню", callback_data="main_menu")],
                ]
                await update.effective_message.reply_text(self._format_search_params(user_id), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
                return

            message = f"🏠 Найдено {len(decent)} подходящих квартир:\n\n"
            for i, apt in enumerate(decent[:5], 1):
                message += f"{i}. {apt}\n\n---\n\n"

            if len(decent) > 5:
                message += f"... и ещё {len(decent) - 5} квартир.\n"

            keyboard = [
                [InlineKeyboardButton("🔄 Обновить поиск", callback_data="search")],
                [InlineKeyboardButton("📋 Все результаты", callback_data="last")],
                [InlineKeyboardButton("🏠 Меню", callback_data="main_menu")],
            ]

            await update.effective_message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
            await update.effective_message.reply_text(self._format_search_params(user_id), parse_mode=ParseMode.HTML)
            logger.info(f"Поиск выполнен: найдено {len(decent)} квартир")

        except Exception as e:
            logger.error(f"Ошибка при поиске: {e}")
            await status_msg.edit_text("❌ Произошла ошибка при поиске.")
            await update.effective_message.reply_text("Попробуйте позже.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]))
    
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /search"""
        user_id = update.effective_user.id
        await self._do_search(update, context, user_id)
    
    async def last_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /last"""
        user_id = update.effective_user.id
        settings = get_user_settings(user_id)
        max_age_days = settings.get("max_publication_age_days", 3)

        if self.last_search_results and self.last_search_time:
            if datetime.now() - self.last_search_time < timedelta(hours=1):
                apartments = self.last_search_results
            else:
                apartments, _ = await get_last_apartments(5, max_age_days)
        else:
            apartments, _ = await get_last_apartments(5, max_age_days)

        if not apartments:
            await update.message.reply_text("😔 Нет сохранённых результатов. Выполните поиск с помощью /search")
            return

        message = "📋 Последние найденные квартиры:\n\n"
        for i, apt in enumerate(apartments, 1):
            message += f"{i}. {apt}\n\n---\n\n"

        keyboard = [
            [InlineKeyboardButton("🔍 Новый поиск", callback_data="search")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="last")],
            [InlineKeyboardButton("🏠 Меню", callback_data="main_menu")],
        ]

        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def subscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /subscribe"""
        user_id = update.effective_user.id
        self.subscribed_users.add(user_id)
        await update.message.reply_text("✅ Вы подписались на ежедневную рассылку! Каждое утро вы будете получать свежие объявления.")
        logger.info(f"Пользователь @{update.effective_user.username or 'unknown'} подписался на рассылку")
    
    async def unsubscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /unsubscribe"""
        user_id = update.effective_user.id
        self.subscribed_users.discard(user_id)
        await update.message.reply_text("❌ Вы отписались от рассылки.")
        logger.info(f"Пользователь @{update.effective_user.username or 'unknown'} отписался от рассылки")
    
    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /settings"""
        user_id = update.effective_user.id
        message = self._format_settings(user_id)
        keyboard = [
            [InlineKeyboardButton("📐 Площадь", callback_data="set_area")],
            [InlineKeyboardButton("💰 Цена", callback_data="set_price")],
            [InlineKeyboardButton("🚪 Комнаты", callback_data="set_rooms")],
            [InlineKeyboardButton("🚿 Санузлы", callback_data="set_bathrooms")],
            [InlineKeyboardButton("📅 Срок давности", callback_data="set_age")],
            [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
        ]
        await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    def _format_search_params(self, user_id: int) -> str:
        """Форматирование параметров поиска"""
        settings = get_user_settings(user_id)
        age_days = settings.get("max_publication_age_days", 3)
        age_label = f"до {age_days} дн." if age_days > 0 else "все"
        return (
            "📋 Параметры поиска:\n"
            f"• Город: Новосибирск\n"
            f"• Площадь: от {settings['min_area']} м²\n"
            f"• Комнат: {settings['min_rooms']} или более\n"
            f"• Санузлов: {settings['min_bathrooms']}\n"
            f"• Цена: до {settings['max_price']:,} ₽\n"
            f"• Срок давности: {age_label}\n\n"
            "🔍 Условия отбора:\n"
            "• Возможна новостройка\n"
            "• Старый фонд — не первый/не последний этаж,\n"
            "  балкон/лоджия, хорошее состояние,\n"
            "  год постройки не старше 1990\n\n"
            "⚠️ <i>При парсинге сайтов возможно потребуется</i>\n"
            "<i>пройти капчу или закрыть всплывающее окно в браузере.</i>"
        )
    
    def _format_settings(self, user_id: int) -> str:
        """Форматирование настроек пользователя"""
        settings = get_user_settings(user_id)
        age_days = settings.get("max_publication_age_days", 3)
        age_label = f"{age_days} дн." if age_days > 0 else "без ограничений"
        return (
            "⚙️ Ваши настройки поиска:\n\n"
            f"📐 Мин. площадь: {settings['min_area']} м²\n"
            f"💰 Макс. цена: {settings['max_price']:,} ₽\n"
            f"🚪 Комнат: {settings['min_rooms']} или более\n"
            f"🚿 Санузлов: {settings['min_bathrooms']} или более\n"
            f"📅 Срок давности: {age_label}\n"
        )
    
    def _format_parsing_error(self, source: str, error_text: str) -> str:
        """Форматирование ошибки парсинга для вывода в чат"""
        error_lower = error_text.lower()
        
        # Определяем тип ошибки и даём рекомендацию
        if "captcha" in error_lower or "капча" in error_lower:
            recommendation = "🔄 Попробуйте позже или обновите cookies"
        elif "429" in error_lower or "too many requests" in error_lower:
            recommendation = "⏳ Слишком частые запросы. Подождите 5-10 минут"
        elif "401" in error_lower or "unauthorized" in error_lower:
            recommendation = "🔒 Требуется авторизация. Сайт недоступен без входа"
        elif "403" in error_lower or "forbidden" in error_lower:
            recommendation = "🚫 Доступ запрещён. Возможно, нужен прокси"
        elif "timeout" in error_lower or "таймаут" in error_lower:
            recommendation = "⏱ Превышено время ожидания. Проверьте интернет"
        elif "connection" in error_lower or "connect" in error_lower:
            recommendation = "🌐 Ошибка подключения. Проверьте интернет-соединение"
        elif "cookie" in error_lower:
            recommendation = "🍪 Нужны обновлённые cookies. Сайт требует авторизацию"
        elif "playwright" in error_lower:
            recommendation = "🎭 Ошибка Playwright. Проверьте установку браузеров"
        elif "ssl" in error_lower or "certificate" in error_lower:
            recommendation = "🔐 Проблема с SSL-сертификатом"
        else:
            recommendation = "💡 Попробуйте позже или проверьте настройки прокси"
        
        return (
            f"❌ {source}: проблема с подключением\n\n"
            f"📋 Ошибка: {error_text[:150]}\n\n"
            f"💡 Рекомендация: {recommendation}"
        )
    
    async def settings_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик кнопки настроек"""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        message = self._format_settings(user_id)
        keyboard = [
            [InlineKeyboardButton("📐 Площадь", callback_data="set_area")],
            [InlineKeyboardButton("💰 Цена", callback_data="set_price")],
            [InlineKeyboardButton("🚪 Комнаты", callback_data="set_rooms")],
            [InlineKeyboardButton("🚿 Санузлы", callback_data="set_bathrooms")],
            [InlineKeyboardButton("📅 Срок давности", callback_data="set_age")],
            [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
        ]
        await self.safe_edit(query, message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def set_param_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик выбора параметра для изменения"""
        query = update.callback_query
        await query.answer()
        param = query.data
        
        if param == "set_area":
            keyboard = [
                [InlineKeyboardButton("80 м²", callback_data="area_80"), InlineKeyboardButton("100 м²", callback_data="area_100")],
                [InlineKeyboardButton("120 м²", callback_data="area_120"), InlineKeyboardButton("150 м²", callback_data="area_150")],
                [InlineKeyboardButton("◀️ Назад", callback_data="settings")],
            ]
            message = "📐 Выберите минимальную площадь:"
        elif param == "set_price":
            keyboard = [
                [InlineKeyboardButton("10 млн ₽", callback_data="price_10000000"), InlineKeyboardButton("14 млн ₽", callback_data="price_14000000")],
                [InlineKeyboardButton("17 млн ₽", callback_data="price_17000000"), InlineKeyboardButton("20 млн ₽", callback_data="price_20000000")],
                [InlineKeyboardButton("◀️ Назад", callback_data="settings")],
            ]
            message = "💰 Выберите максимальную цену:"
        elif param == "set_rooms":
            keyboard = [
                [InlineKeyboardButton("1+", callback_data="rooms_1"), InlineKeyboardButton("2+", callback_data="rooms_2")],
                [InlineKeyboardButton("3+", callback_data="rooms_3"), InlineKeyboardButton("4+", callback_data="rooms_4")],
                [InlineKeyboardButton("◀️ Назад", callback_data="settings")],
            ]
            message = "🚪 Выберите минимальное количество комнат:"
        elif param == "set_bathrooms":
            keyboard = [
                [InlineKeyboardButton("1+", callback_data="bath_1"), InlineKeyboardButton("2+", callback_data="bath_2")],
                [InlineKeyboardButton("◀️ Назад", callback_data="settings")],
            ]
            message = "🚿 Выберите минимальное количество санузлов:"
        elif param == "set_age":
            keyboard = [
                [InlineKeyboardButton("1 день", callback_data="age_1"), InlineKeyboardButton("3 дня", callback_data="age_3")],
                [InlineKeyboardButton("7 дней", callback_data="age_7"), InlineKeyboardButton("14 дней", callback_data="age_14")],
                [InlineKeyboardButton("Без ограничений", callback_data="age_0")],
                [InlineKeyboardButton("◀️ Назад", callback_data="settings")],
            ]
            message = "📅 Выберите максимальный срок давности публикации:"
        else:
            return
        
        await self.safe_edit(query, message, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def apply_setting_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик применения настройки"""
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        data = query.data
        
        if data.startswith("area_"):
            value = int(data.split("_")[1])
            update_user_setting(user_id, "min_area", value)
        elif data.startswith("price_"):
            value = int(data.split("_")[1])
            update_user_setting(user_id, "max_price", value)
        elif data.startswith("rooms_"):
            value = int(data.split("_")[1])
            update_user_setting(user_id, "min_rooms", value)
        elif data.startswith("bath_"):
            value = int(data.split("_")[1])
            update_user_setting(user_id, "min_bathrooms", value)
        elif data.startswith("age_"):
            value = int(data.split("_")[1])
            update_user_setting(user_id, "max_publication_age_days", value)
        else:
            return
        
        message = self._format_settings(user_id)
        keyboard = [
            [InlineKeyboardButton("📐 Площадь", callback_data="set_area")],
            [InlineKeyboardButton("💰 Цена", callback_data="set_price")],
            [InlineKeyboardButton("🚪 Комнаты", callback_data="set_rooms")],
            [InlineKeyboardButton("🚿 Санузлы", callback_data="set_bathrooms")],
            [InlineKeyboardButton("📅 Срок давности", callback_data="set_age")],
            [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
        ]
        await self.safe_edit(query, message, reply_markup=InlineKeyboardMarkup(keyboard))

    async def safe_edit(self, query, text: str, reply_markup=None, parse_mode=None) -> None:
        """Безопасное редактирование сообщения"""
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    
    def update_activity(self, user_id: int) -> None:
        """Обновление времени последней активности"""
        self.user_activity[user_id] = datetime.now()
    
    def track_request(self, user_id: int) -> None:
        """Трекинг запроса пользователя"""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        
        if user_id not in self.user_requests_minute:
            self.user_requests_minute[user_id] = []
        self.user_requests_minute[user_id].append(now)
        self.user_requests_minute[user_id] = [t for t in self.user_requests_minute[user_id] if (now - t).total_seconds() < 60]
        
        if user_id not in self.user_requests_day:
            self.user_requests_day[user_id] = {"date": today, "count": 0}
        if self.user_requests_day[user_id]["date"] != today:
            self.user_requests_day[user_id] = {"date": today, "count": 0}
        self.user_requests_day[user_id]["count"] += 1
    
    def get_user_stats(self, user_id: int) -> dict:
        """Получение статистики пользователя"""
        minute_count = len(self.user_requests_minute.get(user_id, []))
        day_data = self.user_requests_day.get(user_id, {"date": datetime.now().strftime("%Y-%m-%d"), "count": 0})
        if day_data["date"] != datetime.now().strftime("%Y-%m-%d"):
            day_count = 0
        else:
            day_count = day_data["count"]
        return {"minute_count": minute_count, "minute_limit": RATE_LIMIT_PER_MINUTE, "day_count": day_count, "day_limit": DAILY_LIMIT_PER_USER}
    
    def check_rate_limit(self, user_id: int) -> bool:
        """Проверка лимита запросов в минуту"""
        if not DEBUG_MODE:
            return True
        stats = self.get_user_stats(user_id)
        return stats["minute_count"] < stats["minute_limit"]
    
    def check_daily_limit(self, user_id: int) -> bool:
        """Проверка дневного лимита"""
        if not DEBUG_MODE:
            return True
        stats = self.get_user_stats(user_id)
        return stats["day_count"] < stats["day_limit"]
    
    def format_stats(self, user_id: int) -> str:
        """Форматирование статистики"""
        stats = self.get_user_stats(user_id)
        return f"📊 Статистика (debug)\n⏱ За минуту: {stats['minute_count']}/{stats['minute_limit']}\n📅 За сегодня: {stats['day_count']}/{stats['day_limit']}"
    
    def estimate_tokens(self, text: str) -> int:
        """Оценка количества токенов"""
        return len(text) // 4 + 1
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик нажатий на инлайн-кнопки"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "search":
            user_id = update.effective_user.id
            await self._do_search(update, context, user_id)
        elif query.data == "last":
            await self.last_command(update, context)
        elif query.data == "settings":
            await self.settings_callback(update, context)
        elif query.data.startswith("set_"):
            await self.set_param_callback(update, context)
        elif query.data.startswith(("area_", "price_", "rooms_", "bath_", "age_")):
            await self.apply_setting_callback(update, context)
        elif query.data == "main_menu":
            user_id = update.effective_user.id
            keyboard = [
                [InlineKeyboardButton("🔍 Поиск квартир", callback_data="search")],
                [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
                [InlineKeyboardButton("📋 Последние объявления", callback_data="last")],
                [InlineKeyboardButton("📩 Подписаться", callback_data="toggle_subscribe")],
                [InlineKeyboardButton("💬 Обратная связь", callback_data="feedback")],
                [InlineKeyboardButton("🚪 Exit", callback_data="exit_bot")],
            ]
            await self.safe_edit(query, f"🏠 Главное меню\n\n{self._format_search_params(user_id)}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        elif query.data == "toggle_subscribe":
            user_id = update.effective_user.id
            if user_id in self.subscribed_users:
                self.subscribed_users.discard(user_id)
                await self.safe_edit(query, "❌ Вы отписались от рассылки.")
            else:
                self.subscribed_users.add(user_id)
                await self.safe_edit(query, "✅ Вы подписались на рассылку!")
        elif query.data == "feedback":
            await self.safe_edit(query, "💬 Напишите ваше сообщение разработчику. Для отмены нажмите /start")
        elif query.data == "exit_bot":
            await self.safe_edit(query, "👋 Желаю удачи в поиске квартиры! Если захотите вернуться — напишите /start")
        elif query.data == "dashboard":
            report = get_dashboard("today")
            keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]
            await self.safe_edit(query, report, reply_markup=InlineKeyboardMarkup(keyboard))
        elif query.data == "test_parsers":
            await self._test_parsers(update, context)

    async def _test_parsers(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Тест всех парсеров из меню бота (только DEBUG)"""
        query = update.callback_query
        status_msg = await query.message.reply_text("🧪 Запускаю тест парсеров...\n\n⏳ CIAN...")

        import time as _time
        results = []

        # CIAN
        try:
            from parser import parse_cian_playwright
            t0 = _time.time()
            r = await parse_cian_playwright()
            elapsed = _time.time() - t0
            count = len(r) if isinstance(r, list) else 0
            results.append(("CIAN", count, elapsed, r if count else None))
            await status_msg.edit_text(
                f"🧪 Тест парсеров\n\n"
                f"{'✅' if count else '⚠️'} CIAN: {count} квартир ({elapsed:.1f}с)\n"
                f"⏳ N1.RU..."
            )
        except Exception as e:
            results.append(("CIAN", 0, 0, str(e)[:60]))
            await status_msg.edit_text(f"🧪 Тест парсеров\n\n❌ CIAN: {str(e)[:60]}\n⏳ N1.RU...")

        # N1.RU
        try:
            from parser import parse_n1_playwright
            t0 = _time.time()
            r = await parse_n1_playwright()
            elapsed = _time.time() - t0
            count = len(r) if isinstance(r, list) else 0
            results.append(("N1.RU", count, elapsed, r if count else None))
            await status_msg.edit_text(
                f"🧪 Тест парсеров\n\n"
                f"{'✅' if results[0][1] else '⚠️'} {results[0][0]}: {results[0][1]} ({results[0][2]:.1f}с)\n"
                f"{'✅' if count else '⚠️'} N1.RU: {count} квартир ({elapsed:.1f}с)\n"
                f"⏳ Авито (UC)..."
            )
        except Exception as e:
            results.append(("N1.RU", 0, 0, str(e)[:60]))
            await status_msg.edit_text(
                f"🧪 Тест парсеров\n\n"
                f"{'✅' if results[0][1] else '⚠️'} {results[0][0]}: {results[0][1]} ({results[0][2]:.1f}с)\n"
                f"❌ N1.RU: {str(e)[:60]}\n"
                f"⏳ Авито (UC)..."
            )

        # Авито (UC)
        try:
            from parser import parse_avito_playwright
            t0 = _time.time()
            r = await parse_avito_playwright()
            elapsed = _time.time() - t0
            count = len(r) if isinstance(r, list) else 0
            results.append(("Авито", count, elapsed, r if count else None))
            await status_msg.edit_text(
                "🧪 Тест парсеров\n\n" +
                "\n".join(f"{'✅' if n[1] else '⚠️'} {n[0]}: {n[1]} квартир ({n[2]:.1f}с)" for n in results) +
                "\n⏳ Домклик (UC)..."
            )
        except Exception as e:
            results.append(("Авито", 0, 0, str(e)[:60]))
            await status_msg.edit_text(
                "🧪 Тест парсеров\n\n" +
                "\n".join(f"{'✅' if n[1] else '⚠️'} {n[0]}: {n[1]} ({n[2]:.1f}с)" for n in results) +
                f"\n❌ Авито: {str(e)[:60]}" +
                "\n⏳ Домклик (UC)..."
            )

        # Домклик (UC)
        try:
            from parser import parse_domclick_playwright
            t0 = _time.time()
            r = await parse_domclick_playwright()
            elapsed = _time.time() - t0
            count = len(r) if isinstance(r, list) else 0
            results.append(("Домклик", count, elapsed, r if count else None))
        except Exception as e:
            results.append(("Домклик", 0, 0, str(e)[:60]))

        # Итоговый отчёт
        total = sum(n[1] for n in results)
        lines = ["🧪 **Результат теста парсеров**\n"]
        for name, count, elapsed, data in results:
            icon = "✅" if count else ("❌" if isinstance(data, str) else "⚠️")
            if isinstance(data, str):
                lines.append(f"{icon} {name}: {data}")
            else:
                lines.append(f"{icon} {name}: {count} квартир ({elapsed:.1f}с)")
                if count and data:
                    for apt in data[:2]:
                        lines.append(f"   {apt.price:>12,} ₽ | {apt.area:.0f}м² | {apt.rooms}-комн")
        lines.append(f"\n📊 **Итого: {total} квартир**")

        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="main_menu")]]
        await status_msg.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))

    async def send_daily_notifications(self, context: CallbackContext) -> None:
        """Отправка ежедневных уведомлений"""
        if not self.subscribed_users:
            return
        try:
            # Используем дефолтный срок давности из конфига
            apartments, errors = await search_apartments(use_cache=False)
            if not apartments:
                return
            message = "🌅 Доброе утро! Вот свежие квартиры:\n\n"
            for i, apt in enumerate(apartments[:3], 1):
                message += f"{i}. {apt}\n\n---\n\n"
            if errors:
                message += "\n⚠️ Ошибки при парсинге:\n" + "\n".join(errors)
            for user_id in self.subscribed_users:
                try:
                    await context.bot.send_message(chat_id=user_id, text=message)
                except Exception as e:
                    logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при формировании рассылки: {e}")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка входящих сообщений"""
        pass


def create_bot(proxy: str = None):
    """Создание и настройка бота"""
    from telegram.ext import ApplicationBuilder

    bot = ApartmentBot()

    builder = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN)

    if proxy:
        builder = (
            builder
            .proxy(proxy)
            .connect_timeout(60)
            .read_timeout(60)
            .write_timeout(60)
            .pool_timeout(60)
            .get_updates_proxy(proxy)
            .get_updates_connect_timeout(60)
            .get_updates_read_timeout(60)
            .get_updates_write_timeout(60)
            .get_updates_pool_timeout(60)
        )

    application = builder.build()
    
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("search", bot.search_command))
    application.add_handler(CommandHandler("last", bot.last_command))
    application.add_handler(CommandHandler("subscribe", bot.subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", bot.unsubscribe_command))
    application.add_handler(CommandHandler("settings", bot.settings_command))
    application.add_handler(CallbackQueryHandler(bot.button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_daily(bot.send_daily_notifications, time=time(hour=9, minute=0), name="daily_notification")
    
    return application