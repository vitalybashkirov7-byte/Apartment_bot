"""
Модуль парсинга объявлений о продаже квартир с различных сайтов
"""
import asyncio
import logging
import random
import re
import time
import pickle
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from config import (
    CACHE_TTL,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    SEARCH_CONFIG,
    SOURCES,
    USER_AGENT,
    HTTP_PROXY,
    HTTPS_PROXY,
)

logger = logging.getLogger(__name__)

# Кеш для хранения результатов
_cache: dict[str, tuple[float, list["Apartment"]]] = {}

# Ротация User-Agent
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# Попытка импорта curl_cffi для обхода блокировок
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
    logger.info("curl_cffi доступен — используем для обхода блокировок")
except ImportError:
    HAS_CURL_CFFI = False
    logger.info("curl_cffi не установлен — используем aiohttp")


def get_random_ua() -> str:
    """Получить случайный User-Agent"""
    return random.choice(USER_AGENTS)


def _check_robots_txt(url: str, user_agent: str = "*") -> bool:
    """Проверка robots.txt — разрешён ли доступ для парсера.

    Returns:
        True если доступ разрешён (или robots.txt недоступен),
        False если доступ запрещён.
    """
    from urllib.parse import urlparse
    from urllib.robotparser import RobotFileParser

    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        can_fetch = rp.can_fetch(user_agent, url)
        if not can_fetch:
            logger.warning(f"robots.txt запрещает доступ к {url}")
        return can_fetch
    except Exception:
        # Если robots.txt недоступен — разрешаем (но с осторожностью)
        return True


def _kill_chrome():
    """Убить все процессы Chrome/ChromeDriver (нужно между UC-парсерами)"""
    import subprocess
    for proc in ("chrome", "chromedriver"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", f"{proc}.exe", "/T"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
    time.sleep(2)


def get_proxy() -> Optional[dict]:
    """Получить прокси из конфигурации (только для парсинга, НЕ для Telegram)"""
    if HTTP_PROXY or HTTPS_PROXY:
        proxies = {}
        if HTTP_PROXY:
            proxies["http"] = HTTP_PROXY
        if HTTPS_PROXY:
            proxies["https"] = HTTPS_PROXY
        return proxies
    return None


@dataclass
class Apartment:
    """Модель квартиры"""
    source: str
    url: str
    price: int
    area: float
    address: str
    floor: int
    total_floors: int
    rooms: int
    bathrooms: int
    year: Optional[int]
    has_balcony: bool
    condition: str
    description: str
    complex_name: str
    published_date: str

    def __str__(self) -> str:
        return (
            f"🏠 ЖК \"{self.complex_name}\"\n"
            f"📍 Адрес: {self.address}\n"
            f"📐 Площадь: {self.area} м²\n"
            f"🚪 Комнат: {self.rooms}\n"
            f"🚿 Санузлов: {self.bathrooms}\n"
            f"💰 Цена: {self.price:,} ₽\n"
            f"📝 Описание: {self.description}\n"
            f"📅 Дата: {self.published_date}\n"
            f"🔗 Ссылка: {self.url}"
        )


async def fetch_page_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    max_retries: int = 3,
    source: str = ""
) -> Optional[str]:
    """Загрузка страницы с повторными попытками и поддержкой curl_cffi"""
    
    if HAS_CURL_CFFI:
        return await fetch_with_curl(url, max_retries, source)
    
    proxy = get_proxy()
    
    for attempt in range(max_retries):
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=30),
                proxy=proxy.get("http") if proxy else None
            ) as response:
                if response.status == 200:
                    return await response.text()
                elif response.status == 429:
                    wait = (2 ** attempt) * 5
                    logger.warning(f"{source}: HTTP 429, ожидание {wait}с (попытка {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait)
                    continue
                elif response.status == 401:
                    logger.warning(f"{source}: HTTP 401 — требуется авторизация")
                    return None
                else:
                    logger.warning(f"{source}: HTTP {response.status}")
                    return None
        except asyncio.TimeoutError:
            logger.warning(f"{source}: Таймаут (попытка {attempt + 1}/{max_retries})")
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"{source}: Ошибка загрузки: {e}")
            return None
    
    logger.error(f"{source}: Все попытки загрузки исчерпаны")
    return None


async def fetch_with_curl(url: str, max_retries: int = 3, source: str = "") -> Optional[str]:
    """Загрузка через curl_cffi (лучше обходит антибот-защиту)"""
    import concurrent.futures
    
    proxy = get_proxy()
    proxy_url = proxy.get("http") if proxy else None
    
    for attempt in range(max_retries):
        try:
            loop = asyncio.get_event_loop()
            
            def _fetch():
                return curl_requests.get(
                    url,
                    impersonate="chrome120",
                    proxies={"http": proxy_url, "https": proxy_url} if proxy_url else None,
                    timeout=30
                )
            
            response = await loop.run_in_executor(None, _fetch)
            
            if response.status_code == 200:
                return response.text
            elif response.status_code == 429:
                wait = (2 ** attempt) * 5
                logger.warning(f"{source}: HTTP 429 (curl), ожидание {wait}с")
                await asyncio.sleep(wait)
                continue
            elif response.status_code == 401:
                logger.warning(f"{source}: HTTP 401 — требуется авторизация")
                return None
            else:
                logger.warning(f"{source}: HTTP {response.status_code} (curl)")
                return None
                
        except Exception as e:
            logger.error(f"{source}: Ошибка curl_cffi: {e}")
            await asyncio.sleep(2)
    
    return None


def parse_price(text: str) -> Optional[int]:
    """Извлечение цены из текста"""
    digits = re.sub(r"[^\d]", "", text)
    if digits:
        return int(digits)
    return None


def parse_area(text: str) -> Optional[float]:
    """Извлечение площади из текста"""
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if match:
        return float(match.group(1).replace(",", "."))
    return None


def parse_floor(text: str) -> Optional[tuple[int, int]]:
    """Извлечение этажа (этаж/всего этажей)"""
    match = re.search(r"(\d+)/(\d+)", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def parse_rooms(text: str) -> int:
    """Извлечение количества комнат"""
    match = re.search(r"(\d+)\s*(?:комн|ком\.|комнат)", text.lower())
    if match:
        return int(match.group(1))
    return 1


def parse_bathrooms(text: str) -> int:
    """Извлечение количества санузлов"""
    text_lower = text.lower()
    if "2 санузла" in text_lower or "два санузла" in text_lower or "2 совмещен" in text_lower or "2 раздельн" in text_lower:
        return 2
    if "санузел" in text_lower or "санузл" in text_lower:
        return 1
    return 1


def has_balcony(text: str) -> bool:
    """Проверка наличия балкона/лоджии"""
    text_lower = text.lower()
    return any(word in text_lower for word in ["балкон", "лоджи", "лоджия"])


def get_condition(text: str) -> str:
    """Определение состояния квартиры"""
    text_lower = text.lower()
    if "евроремонт" in text_lower or "евро" in text_lower:
        return "евроремонт"
    elif "хорошее" in text_lower or "отличное" in text_lower or "ремонт" in text_lower:
        return "хорошее"
    elif "среднее" in text_lower:
        return "среднее"
    return "не указано"


def is_new_building(text: str) -> bool:
    """Проверка, является ли квартира новостройкой"""
    text_lower = text.lower()
    return any(word in text_lower for word in [
        "новострой", "новостройк", "сдача", "сдан", "ввод в эксплуатацию",
        "постройка 202", "постройка 201", "год постройки 202", "год постройки 201"
    ])


# Маппинг месяцев для парсинга русских дат
_RU_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    "янв": 1, "фев": 2, "мар": 3, "апр": 4,
    "май": 5, "июн": 6, "июл": 7, "авг": 8,
    "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


def parse_publication_date(text: str) -> Optional[datetime]:
    """Парсинг даты публикации из текста объявления.

    Поддерживает форматы:
    - «Сегодня», «Вчера»
    - «N минут/часов/дней назад»
    - «17 июля», «17.07.2026», «2026-07-17»
    """
    if not text:
        return None

    now = datetime.now()
    text_lower = text.lower().strip()

    # «Сегодня» / «Вчера»
    if "сегодня" in text_lower:
        return now
    if "вчера" in text_lower:
        return now - timedelta(days=1)

    # «N минут/часов/дн/дней/недел/месяц/год назад»
    m = re.search(r"(\d+)\s*(минут|час|дн|дней|день|недел|неделю|месяц|год|лет)\w*\s*назад", text_lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "минут" in unit:
            return now - timedelta(minutes=n)
        if "час" in unit:
            return now - timedelta(hours=n)
        if "дн" in unit or "день" in unit:
            return now - timedelta(days=n)
        if "недел" in unit:
            return now - timedelta(weeks=n)
        if "месяц" in unit:
            return now - timedelta(days=n * 30)
        if "год" in unit or "лет" in unit:
            return now - timedelta(days=n * 365)

    # «17 июля» / «17 июля 2026»
    m = re.search(r"(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?", text_lower)
    if m:
        day = int(m.group(1))
        month_name = m.group(2)
        year = int(m.group(3)) if m.group(3) else now.year
        month = _RU_MONTHS.get(month_name)
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                pass

    # «17.07.2026» / «2026-07-17»
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    return None


def is_publication_fresh(apt: "Apartment", max_age_days: int) -> bool:
    """Проверка, укладывается ли публикация в допустимый срок давности."""
    if max_age_days <= 0:
        return True

    pub_date = parse_publication_date(apt.published_date)
    if pub_date is None:
        # Если дата неизвестна — пропускаем фильтр (не отбрасываем объявление)
        return True

    age = datetime.now() - pub_date
    return age.days <= max_age_days


def is_decent_apartment(apt: Apartment, max_age_days: int = 0) -> bool:
    """Проверка, является ли квартира 'приличной'"""
    # Фильтр по сроку давности публикации
    if not is_publication_fresh(apt, max_age_days):
        return False

    is_new = is_new_building(apt.description) or (apt.year and apt.year >= 2015)

    if is_new:
        return (
            apt.rooms >= SEARCH_CONFIG["min_rooms"]
            and apt.bathrooms >= SEARCH_CONFIG["min_bathrooms"]
        )

    # Обязательные фильтры
    required = {
        "not_first_floor": apt.floor > 1,
        "not_last_floor": apt.floor < apt.total_floors,
        "enough_rooms": apt.rooms >= SEARCH_CONFIG["min_rooms"],
        "enough_bathrooms": apt.bathrooms >= SEARCH_CONFIG["min_bathrooms"],
    }

    # Желательные (хотя бы 2 из 3)
    preferred = sum([
        apt.has_balcony,
        apt.condition in ["хорошее", "евроремонт"],
        apt.year is None or apt.year >= SEARCH_CONFIG["max_year"],
    ])

    return all(required.values()) and preferred >= 1


async def parse_cian(session: aiohttp.ClientSession) -> list[Apartment]:
    """Парсинг объявлений с Циан (актуальные селекторы)"""
    apartments = []
    try:
        params = {
            "city": "2",
            "minarea": str(SEARCH_CONFIG["min_area"]),
            "maxprice": str(SEARCH_CONFIG["max_price"]),
        }
        url = f"{SOURCES['cian']}/cat.php?{'&'.join(f'{k}={v}' for k, v in params.items())}"
        
        html = await fetch_page_with_retry(session, url, source="Циан")
        if not html:
            return apartments

        soup = BeautifulSoup(html, "html.parser")
        
        # Ищем все карточки объявлений
        # По данным с сайта, класс выглядит как x31de4314--_5d947--wrapper
        cards = soup.find_all("div", class_=re.compile(r"x31de4314--_5d947--wrapper"))
        
        if not cards:
            # Запасной вариант: ищем по data-name
            cards = soup.find_all("div", {"data-name": "CardComponent"})
        
        if not cards:
            # Ещё запасной: ищем любые div с карточками
            cards = soup.find_all("div", class_=re.compile(r"card|offer|item"))
        
        logger.info(f"Циан: найдено карточек: {len(cards)}")
        
        for card in cards[:20]:
            try:
                # Извлекаем текст всей карточки для поиска данных
                card_text = card.get_text(" ", strip=True)
                
                # Цена — ищем число с ₽
                price_match = re.search(r"([\d\s]+)₽", card_text)
                if not price_match:
                    continue
                price = int(re.sub(r"\s", "", price_match.group(1)))
                if price > SEARCH_CONFIG["max_price"]:
                    continue
                
                # Площадь — ищем число с м²
                area_match = re.search(r"(\d+[\.,]?\d*)\s*м²", card_text)
                if not area_match:
                    continue
                area = float(area_match.group(1).replace(",", "."))
                if area < SEARCH_CONFIG["min_area"]:
                    continue
                
                # Комнаты — ищем в тексте
                rooms_match = re.search(r"(\d+)-[кк]омн", card_text)
                rooms = int(rooms_match.group(1)) if rooms_match else 0
                if rooms < SEARCH_CONFIG["min_rooms"]:
                    continue
                
                # Ссылка
                link_elem = card.find("a", href=re.compile(r"/sale/flat/"))
                if not link_elem:
                    # Пробуем найти любую ссылку
                    link_elem = card.find("a", href=True)
                if not link_elem:
                    continue
                
                apt_url = link_elem.get("href", "")
                if not apt_url.startswith("http"):
                    apt_url = SOURCES["cian"] + apt_url
                
                # Адрес — ищем в тексте
                address_match = re.search(r"(ул\.|пр\.|пл\.|пер\.|шоссе|бульвар|проезд|наб\.|Новосибирск)[^,.]*", card_text)
                address = address_match.group(0) if address_match else "Новосибирск"
                
                # Описание — берём из карточки
                desc_elem = card.find("h2") or card.find("h3") or card.find("p")
                description = desc_elem.text.strip() if desc_elem else card_text[:200]
                
                # Этаж
                floor_match = re.search(r"(\d+)/(\d+)", card_text)
                if floor_match:
                    floor = int(floor_match.group(1))
                    total_floors = int(floor_match.group(2))
                else:
                    floor = 1
                    total_floors = 10

                # Дата публикации
                date_match = re.search(
                    r"(\d{1,2}[\s.\-/]*(?:янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)\w*[\s.\-/]*\d{0,4}|\d{1,2}[\s.\-/]*\d{1,2}[\s.\-/]*\d{4})",
                    card_text, re.IGNORECASE
                )
                published_date = date_match.group(0).strip() if date_match else ""

                apt = Apartment(
                    source="cian",
                    url=apt_url,
                    price=price,
                    area=area,
                    address=address[:100],
                    floor=floor,
                    total_floors=total_floors,
                    rooms=rooms,
                    bathrooms=1,
                    year=None,
                    has_balcony=has_balcony(card_text),
                    condition=get_condition(card_text),
                    description=description[:200],
                    complex_name="ЖК",
                    published_date=published_date,
                )
                apartments.append(apt)
                
            except Exception as e:
                logger.error(f"Циан: ошибка парсинга карточки: {e}")
                continue

        logger.info(f"Циан: найдено {len(apartments)} объявлений")
        
    except Exception as e:
        logger.error(f"Циан: ошибка парсинга: {e}")
    
    await asyncio.sleep(REQUEST_DELAY)
    return apartments


async def parse_cian_playwright() -> list[Apartment]:
    """Парсинг объявлений с Циан через Playwright Async API (fallback при блокировке HTTP)"""
    apartments = []
    try:
        # Проверка robots.txt
        cian_url = f"{SOURCES['cian']}/cat.php?deal_type=sale&offer_type=flat&region=4897"
        if not _check_robots_txt(cian_url):
            logger.warning("Циан: robots.txt запрещает парсинг — пропускаем")
            return apartments

        PROXY = os.getenv("HTTP_PROXY")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={"server": PROXY} if PROXY else None,
                args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"],
            )

            context = await browser.new_context(
                user_agent=get_random_ua(),
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
            )

            page = await context.new_page()

            # Формируем URL поиска Циан (продажа квартир, Новосибирск)
            url = (
                f"{SOURCES['cian']}/cat.php?"
                f"deal_type=sale"
                f"&engine_version=2"
                f"&offer_type=flat"
                f"&region=4897"
                f"&minarea={SEARCH_CONFIG['min_area']}"
                f"&maxprice={SEARCH_CONFIG['max_price']}"
                f"&rooms%5B0%5D=3&rooms%5B1%5D=4&rooms%5B2%5D=5"
            )

            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            # Ждём загрузки карточек (JS-рендеринг)
            try:
                await page.wait_for_selector(
                    '[data-name="CardComponent"], [data-name="OffersSerpItem"]',
                    timeout=15000,
                )
            except Exception:
                logger.warning("Циан (Playwright): карточки не появились за 15с, пробуем парсить как есть")

            content = await page.content()
            page_title = await page.title()
            logger.info(f"Циан (Playwright): title={page_title[:80]}, content length={len(content)}")

            # Проверяем на блокировку
            if "доступ ограничен" in content.lower() or "подтвердите, что вы не робот" in content.lower():
                logger.warning("Циан (Playwright): запросил капчу / блокировка")
                await browser.close()
                return apartments

            # Пробуем多种 селекторов карточек
            items = (
                await page.query_selector_all('[data-name="CardComponent"]')
                or await page.query_selector_all('[data-name="OffersSerpItem"]')
                or await page.query_selector_all('div[data-name="CardComponent"]')
                or await page.query_selector_all('article')
            )
            logger.info(f"Циан (Playwright): найдено элементов: {len(items)}")

            for item in items[:25]:
                try:
                    card_text = await item.inner_text()
                    lines = [l.strip() for l in card_text.split("\n") if l.strip()]

                    # Цена — ищем строку с ₽ (не ₽/м²)
                    price = None
                    for line in lines:
                        if "₽" in line and "₽/м²" not in line:
                            price = parse_price(line)
                            if price:
                                break
                    if not price or price > SEARCH_CONFIG["max_price"]:
                        continue

                    # Площадь и комнаты — ищем строку вида "3-комн. квартира, 72,4 м², 8/19 этаж"
                    area = 0.0
                    rooms = 0
                    floor = 1
                    total_floors = 10
                    for line in lines:
                        m_area = re.search(r"(\d+[\.,]?\d*)\s*м²", line)
                        m_rooms = re.search(r"(\d+)-[кк]омн", line)
                        m_floor = re.search(r"(\d+)/(\d+)\s*этаж", line)
                        if m_area:
                            area = float(m_area.group(1).replace(",", "."))
                        if m_rooms:
                            rooms = int(m_rooms.group(1))
                        if m_floor:
                            floor = int(m_floor.group(1))
                            total_floors = int(m_floor.group(2))
                    if area < SEARCH_CONFIG["min_area"] or rooms < SEARCH_CONFIG["min_rooms"]:
                        continue

                    # Ссылка (только продажа)
                    link_elem = await item.query_selector("a[href*='/sale/flat/']")
                    if not link_elem:
                        link_elem = await item.query_selector("a[href]")
                    if not link_elem:
                        continue
                    href = await link_elem.get_attribute("href") or ""
                    # Циан может использовать novosibirsk.cian.ru — приводим к www.cian.ru
                    apt_url = href if href.startswith("http") else SOURCES["cian"] + href
                    apt_url = apt_url.replace("novosibirsk.cian.ru", "www.cian.ru")

                    # Адрес — ищем строку с "Новосибирск" или "ул." / "пр." / "шоссе"
                    address = "Новосибирск"
                    for line in lines:
                        if "Новосибирск" in line and "область" not in line.lower():
                            address = line[:100]
                            break
                        if re.search(r"(ул\.|пр\.|пл\.|шоссе|проспект|бульвар)", line, re.IGNORECASE):
                            address = line[:100]
                            break

                    # Описание — заголовок карточки (3-комн. квартира...)
                    description = next((l for l in lines if "комн" in l or "квартир" in l), card_text[:200])

                    # Дата публикации
                    published_date = ""
                    for line in lines:
                        if re.search(r"\d{1,2}\s*(?:янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)", line, re.IGNORECASE):
                            published_date = line[:50]
                            break

                    apt = Apartment(
                        source="cian",
                        url=apt_url,
                        price=price,
                        area=area,
                        address=address[:100],
                        floor=floor,
                        total_floors=total_floors,
                        rooms=rooms,
                        bathrooms=1,
                        year=None,
                        has_balcony=has_balcony(card_text),
                        condition=get_condition(card_text),
                        description=description[:200],
                        complex_name="ЖК",
                        published_date=published_date,
                    )
                    apartments.append(apt)

                except Exception as e:
                    logger.error(f"Циан (Playwright): ошибка парсинга карточки: {e}")
                    continue

            await browser.close()

        logger.info(f"Циан (Playwright): найдено {len(apartments)} объявлений")

    except Exception as e:
        logger.error(f"Циан (Playwright): ошибка парсинга: {e}")

    return apartments


async def parse_n1_playwright() -> list[Apartment]:
    """Парсинг объявлений с N1.RU через Playwright Async API (fallback при блокировке HTTP)"""
    apartments = []
    try:
        # Проверка robots.txt
        n1_url = "https://novosibirsk.n1.ru/kupit/kvartiry/"
        if not _check_robots_txt(n1_url):
            logger.warning("N1.RU: robots.txt запрещает парсинг — пропускаем")
            return apartments

        PROXY = os.getenv("HTTP_PROXY")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={"server": PROXY} if PROXY else None,
                args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"],
            )

            context = await browser.new_context(
                user_agent=get_random_ua(),
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
            )

            page = await context.new_page()

            # Правильный URL для Новосибирска (не n1.ru/realty/...)
            # N1.RU не поддерживает URL-фильтрацию по площади/цене — фильтруем локально
            url = "https://novosibirsk.n1.ru/kupit/kvartiry/"

            await page.goto(url, timeout=60000, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector("article", timeout=15000)
            except Exception:
                logger.warning("N1.RU (Playwright): карточки не появились за 15с")

            content = await page.content()
            page_title = await page.title()
            logger.info(f"N1.RU (Playwright): title={page_title[:80]}, content length={len(content)}")

            # Проверяем на блокировку
            if "доступ ограничен" in content.lower() or "подтвердите" in content.lower():
                logger.warning("N1.RU (Playwright): запросил капчу / блокировка")
                await browser.close()
                return apartments

            items = await page.query_selector_all("article")
            logger.info(f"N1.RU (Playwright): найдено {len(items)} article элементов")

            for item in items[:25]:
                try:
                    card_text = await item.inner_text()
                    lines = [l.strip() for l in card_text.split("\n") if l.strip()]

                    # Цена — ищем строку с数字 (цена без ₽, исключая цену за м²)
                    price = None
                    for line in lines:
                        if "₽" in line:
                            price = parse_price(line)
                            if price:
                                break
                    if not price:
                        # Пробуем найти отдельную строку с数字 (цена без ₽)
                        for line in lines:
                            # Пропускаем строки с ценой за м²
                            if "/м" in line or "₽/м" in line:
                                continue
                            cleaned = re.sub(r"[^\d]", "", line)
                            if cleaned and len(cleaned) >= 6:
                                try:
                                    p_val = int(cleaned)
                                    if 100000 < p_val < SEARCH_CONFIG["max_price"] * 2:
                                        price = p_val
                                        break
                                except ValueError:
                                    pass
                    if not price or price > SEARCH_CONFIG["max_price"]:
                        if price:
                            logger.debug(f"N1.RU: пропуск — цена {price:,} > {SEARCH_CONFIG['max_price']:,}")
                        continue

                    # Площадь и этаж
                    area = 0.0
                    floor = 1
                    total_floors = 10
                    rooms = 0
                    for line in lines:
                        m_area = re.search(r"(\d+[\.,]?\d*)\s*м[²2]", line)
                        m_floor = re.search(r"(\d+)\s*/\s*(\d+)\s*этаж", line)
                        m_rooms = re.search(r"(\d+)-[кк]", line)
                        if m_area:
                            area = float(m_area.group(1).replace(",", "."))
                        if m_floor:
                            floor = int(m_floor.group(1))
                            total_floors = int(m_floor.group(2))
                        if m_rooms:
                            rooms = int(m_rooms.group(1))
                    if area < SEARCH_CONFIG["min_area"]:
                        logger.debug(f"N1.RU: пропуск — площадь {area} < {SEARCH_CONFIG['min_area']}")
                        continue
                    if rooms and rooms < SEARCH_CONFIG["min_rooms"]:
                        logger.debug(f"N1.RU: пропуск — комнат {rooms} < {SEARCH_CONFIG['min_rooms']}")
                        continue

                    # Ссылка (ищем /view/NNNNN/)
                    link_elem = await item.query_selector("a[href*='/view/']")
                    if not link_elem:
                        link_elem = await item.query_selector("a[href]")
                    if not link_elem:
                        continue
                    href = await link_elem.get_attribute("href") or ""
                    apt_url = href if href.startswith("http") else f"https://novosibirsk.n1.ru{href}"

                    # Адрес — первая строка или строка с адресом
                    address = "Новосибирск"
                    for line in lines:
                        if re.search(r"(ул\.|пр\.|пл\.|шоссе|проспект|бульвар|наб\.|пер\.)", line, re.IGNORECASE):
                            address = line[:100]
                            break
                        if "Новосибирск" in line:
                            address = line[:100]
                            break

                    # Описание — заголовок (первые строки до "Показать контакты")
                    description = ""
                    for line in lines:
                        if "к," in line or "комн" in line:
                            description = line[:200]
                            break
                    if not description:
                        description = card_text[:200].split("Показать")[0]

                    # Дата публикации
                    published_date = ""
                    for line in lines:
                        if re.search(r"\d{1,2}\s*(?:янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)", line, re.IGNORECASE):
                            published_date = line[:50]
                            break

                    apt = Apartment(
                        source="n1",
                        url=apt_url,
                        price=price,
                        area=area,
                        address=address[:100],
                        floor=floor,
                        total_floors=total_floors,
                        rooms=rooms if rooms else parse_rooms(description),
                        bathrooms=parse_bathrooms(description),
                        year=None,
                        has_balcony=has_balcony(card_text),
                        condition=get_condition(card_text),
                        description=description[:200],
                        complex_name="",
                        published_date=published_date,
                    )
                    apartments.append(apt)

                except Exception as e:
                    logger.error(f"N1.RU (Playwright): ошибка парсинга карточки: {e}")
                    continue

            await browser.close()

        logger.info(f"N1.RU (Playwright): найдено {len(apartments)} объявлений")

    except Exception as e:
        logger.error(f"N1.RU (Playwright): ошибка парсинга: {e}")

    return apartments


async def parse_domclick_playwright() -> list[Apartment]:
    """Парсинг объявлений с Домклик через undetected-chromedriver.

    Домклик использует Qrator anti-bot — Playwright/headless блокируется.
    UC non-headless обходит защиту. Парсер best-effort: если UC не запустился
    или карточки не найдены — возвращаем пустой список.
    """
    apartments = []

    def _parse_sync():
        """Синхронный парсинг в отдельном потоке (UC = Selenium = sync)"""
        try:
            import undetected_chromedriver as uc
            import tempfile
        except ImportError:
            logger.warning("Домклик: undetected-chromedriver не установлен")
            return []

        # Очищаем прокси — DomClick не требует его, а прокси ломает UC
        saved_http = os.environ.pop("HTTP_PROXY", None)
        saved_https = os.environ.pop("HTTPS_PROXY", None)
        saved_http_lower = os.environ.pop("http_proxy", None)
        saved_https_lower = os.environ.pop("https_proxy", None)

        tmp_dir = tempfile.mkdtemp(prefix="domclick_")
        apts = []
        driver = None

        try:
            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--lang=ru-RU")
            options.add_argument(f"--user-data-dir={tmp_dir}")

            driver_path = os.path.join(os.path.expanduser("~"), "AppData", "Local", "undetected_chromedriver", "chromedriver.exe")
            driver = uc.Chrome(options=options, headless=False, version_main=150, driver_executable_path=driver_path)
            # URL с фильтрами — без них страница тяжёлая и крашится
            url = (
                "https://novosibirsk.domclick.ru/search?"
                "deal_type=sale&category=living&offer_type=flat"
                f"&rooms={SEARCH_CONFIG['min_rooms']}"
                f"&priceMax={SEARCH_CONFIG['max_price']}"
                f"&areaMin={SEARCH_CONFIG['min_area']}"
            )
            driver.get(url)
            time.sleep(25)

            if "403" in driver.title:
                logger.warning("Домклик (UC): 403 Forbidden")
                return []

            # Карточки — data-test селектор
            # product-snippet-property-offer содержит только房间/площадь/этаж,
            # нужен parent с ценой и адресом
            raw_cards = driver.find_elements("css selector", '[data-test="product-snippet-property-offer"]')
            logger.info(f"Домклик (UC): найдено {len(raw_cards)} элементов")

            # Извлекаем полные данные через JS (поднимаемся к parent)
            cards = driver.execute_script("""
                const items = document.querySelectorAll('[data-test="product-snippet-property-offer"]');
                const results = [];
                items.forEach(item => {
                    let el = item;
                    for (let i = 0; i < 5; i++) {
                        el = el.parentElement;
                        if (el && el.innerText && el.innerText.includes('₽') && el.innerText.includes('м²')) {
                            results.push(el.innerText);
                            break;
                        }
                    }
                });
                return results;
            """)
            logger.info(f"Домклик (UC): получено {len(cards)} карточек с данными")

            for text in cards:
                try:
                    lines = [l.strip() for l in text.split("\n") if l.strip()]

                    # Цена
                    price = None
                    for line in lines:
                        if "₽" in line and "/м" not in line:
                            digits = re.sub(r"[^\d]", "", line)
                            if digits and len(digits) >= 6:
                                price = int(digits)
                                break

                    # Площадь
                    area = 0.0
                    for line in lines:
                        m = re.search(r"(\d+[\.,]?\d*)\s*м[²2]", line)
                        if m:
                            area = float(m.group(1).replace(",", "."))
                            break

                    # Этаж
                    floor = 1
                    total_floors = 10
                    for line in lines:
                        m = re.search(r"(\d+)/(\d+)\s*эт", line)
                        if m:
                            floor = int(m.group(1))
                            total_floors = int(m.group(2))
                            break

                    # Комнаты
                    rooms = 0
                    for line in lines:
                        m = re.search(r"(\d+)-[кк]омн", line)
                        if m:
                            rooms = int(m.group(1))
                            break

                    # Адрес
                    address = "Новосибирск"
                    for line in lines:
                        if "Новосибирск" in line and len(line) < 100:
                            address = line
                            break

                    # Дата
                    published_date = ""
                    for line in lines:
                        if re.search(r"\d+\s*(?:дн|час|мин|нед|мес)\w*\s*назад|вчера|сегодня", line, re.IGNORECASE):
                            published_date = line
                            break

                    if not price or price > SEARCH_CONFIG["max_price"]:
                        continue
                    if area < SEARCH_CONFIG["min_area"]:
                        continue

                    # Ссылка — ищем в тексте URL /offer/...
                    apt_url = "https://novosibirsk.domclick.ru/"
                    offer_match = re.search(r"novosibirsk\.domclick\.ru/\d+", text)
                    if offer_match:
                        apt_url = f"https://{offer_match.group(0)}"

                    apts.append(Apartment(
                        source="domclick",
                        url=apt_url,
                        price=price,
                        area=area,
                        address=address,
                        floor=floor,
                        total_floors=total_floors,
                        rooms=rooms if rooms else parse_rooms(text),
                        bathrooms=parse_bathrooms(text),
                        year=None,
                        has_balcony=has_balcony(text),
                        condition=get_condition(text),
                        description=text[:200],
                        complex_name="",
                        published_date=published_date,
                    ))

                except Exception:
                    continue

            try:
                driver.quit()
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"Домклик (UC): ошибка — {e}")
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            # Восстанавливаем прокси
            if saved_http:
                os.environ["HTTP_PROXY"] = saved_http
            if saved_https:
                os.environ["HTTPS_PROXY"] = saved_https
            if saved_http_lower:
                os.environ["http_proxy"] = saved_http_lower
            if saved_https_lower:
                os.environ["https_proxy"] = saved_https_lower
            # Чистим temp
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

        return apts

    try:
        apartments = await asyncio.to_thread(_parse_sync)
    except Exception as e:
        logger.error(f"Домклик (UC): ошибка потока — {e}")

    logger.info(f"Домклик (UC): найдено {len(apartments)} объявлений")
    return apartments


async def parse_avito_playwright() -> list[Apartment]:
    """Парсинг объявлений с Авито через undetected-chromedriver.

    Playwright/headless блокируется Авито даже с cookies.
    UC non-headless обходит anti-bot. Best-effort.
    """

    def _parse_sync():
        try:
            import undetected_chromedriver as uc
            import tempfile
        except ImportError:
            logger.warning("Авито: undetected-chromedriver не установлен")
            return []

        saved_http = os.environ.pop("HTTP_PROXY", None)
        saved_https = os.environ.pop("HTTPS_PROXY", None)
        saved_http_l = os.environ.pop("http_proxy", None)
        saved_https_l = os.environ.pop("https_proxy", None)

        _kill_chrome()
        tmp_dir = tempfile.mkdtemp(prefix="avito_")
        apts = []
        driver = None

        try:
            options = uc.ChromeOptions()
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--lang=ru-RU")
            options.add_argument(f"--user-data-dir={tmp_dir}")

            driver_path = os.path.join(os.path.expanduser("~"), "AppData", "Local", "undetected_chromedriver", "chromedriver.exe")
            driver = uc.Chrome(options=options, headless=False, version_main=150, driver_executable_path=driver_path)

            url = "https://www.avito.ru/novosibirsk/kvartiry/prodam?price=14000000-17000000&params=202_3000"
            driver.get(url)
            time.sleep(15)

            try:
                content = driver.page_source or ""
            except Exception as e:
                logger.warning(f"Авито (UC): не удалось получить page_source — {e}")
                return []

            if "доступ ограничен" in content.lower() or "проверка безопасности" in content.lower():
                logger.warning("Авито (UC): запросил капчу")
                return []

            items = driver.find_elements("css selector", 'div[data-marker="item"]')
            logger.info(f"Авито (UC): найдено {len(items)} объявлений")

            for item in items[:20]:
                try:
                    text = item.text
                    lines = [l.strip() for l in text.split("\n") if l.strip()]

                    # Цена
                    price = None
                    for line in lines:
                        if "₽" in line:
                            price = parse_price(line)
                            if price:
                                break

                    # Площадь
                    area = 0.0
                    for line in lines:
                        m = re.search(r"(\d+[\.,]?\d*)\s*м[²2]", line)
                        if m:
                            area = float(m.group(1).replace(",", "."))
                            break

                    # Этаж
                    floor = 1
                    total_floors = 10
                    for line in lines:
                        m = re.search(r"(\d+)/(\d+)\s*этаж", line)
                        if m:
                            floor = int(m.group(1))
                            total_floors = int(m.group(2))
                            break

                    # Комнаты
                    rooms = 0
                    for line in lines:
                        m = re.search(r"(\d+)-[кк]", line)
                        if m:
                            rooms = int(m.group(1))
                            break

                    # Адрес
                    address = "Новосибирск"
                    for line in lines:
                        if "Новосибирск" in line and len(line) < 100:
                            address = line
                            break

                    # Ссылка
                    apt_url = "https://www.avito.ru/"
                    try:
                        link = item.find_element("css selector", 'a[data-marker="item-title"]')
                        apt_url = link.get_attribute("href") or apt_url
                    except Exception:
                        pass

                    # Дата
                    published_date = ""
                    for line in lines:
                        if re.search(r"сегодня|вчера|назад|\d+\s*(?:янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек)", line, re.IGNORECASE):
                            published_date = line[:50]
                            break

                    if not price or price > SEARCH_CONFIG["max_price"]:
                        continue
                    if area < SEARCH_CONFIG["min_area"]:
                        continue
                    if rooms and rooms < SEARCH_CONFIG["min_rooms"]:
                        continue

                    apts.append(Apartment(
                        source="avito",
                        url=apt_url,
                        price=price,
                        area=area,
                        address=address,
                        floor=floor,
                        total_floors=total_floors,
                        rooms=rooms,
                        bathrooms=1,
                        year=None,
                        has_balcony=has_balcony(text),
                        condition=get_condition(text),
                        description=text[:200],
                        complex_name="",
                        published_date=published_date,
                    ))

                except Exception:
                    continue

            try:
                driver.quit()
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"Авито (UC): ошибка — {e}")
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            if saved_http:
                os.environ["HTTP_PROXY"] = saved_http
            if saved_https:
                os.environ["HTTPS_PROXY"] = saved_https
            if saved_http_l:
                os.environ["http_proxy"] = saved_http_l
            if saved_https_l:
                os.environ["https_proxy"] = saved_https_l
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

        return apts

    try:
        apartments = await asyncio.to_thread(_parse_sync)
    except Exception as e:
        logger.error(f"Авито (UC): ошибка потока — {e}")

    logger.info(f"Авито (UC): найдено {len(apartments)} объявлений")
    return apartments


async def parse_n1(session: aiohttp.ClientSession) -> list[Apartment]:
    """Парсинг объявлений с N1.RU (актуальные селекторы)"""
    apartments = []
    try:
        params = {
            "minarea": str(SEARCH_CONFIG["min_area"]),
            "maxprice": str(SEARCH_CONFIG["max_price"]),
        }
        url = f"{SOURCES['n1']}/realty/novosibirsk/kvartiry/kupit/?{'&'.join(f'{k}={v}' for k, v in params.items())}"
        
        html = await fetch_page_with_retry(session, url, source="N1.RU")
        if not html:
            return apartments

        soup = BeautifulSoup(html, "html.parser")
        
        cards = (
            soup.find_all("div", class_=re.compile(r"card|item|listing|offer")) or
            soup.find_all("article", class_=re.compile(r"card|item"))
        )
        
        for card in cards[:20]:
            try:
                link_elem = (
                    card.find("a", href=re.compile(r"/realty/")) or
                    card.find("a", href=re.compile(r"/kupit/"))
                )
                if not link_elem:
                    continue
                apt_url = link_elem.get("href", "")
                if not apt_url.startswith("http"):
                    apt_url = SOURCES["n1"] + apt_url

                price_elem = card.find(string=re.compile(r"\d+\s*₽"))
                price = parse_price(str(price_elem)) if price_elem else None
                if not price or price > SEARCH_CONFIG["max_price"]:
                    continue

                area_elem = card.find(string=re.compile(r"\d+\s*м²"))
                area = parse_area(str(area_elem)) if area_elem else None
                if not area or area < SEARCH_CONFIG["min_area"]:
                    continue

                desc_elem = (
                    card.find("p") or
                    card.find("div", class_=re.compile(r"desc|info|text"))
                )
                description = desc_elem.text.strip() if desc_elem else ""

                # Дата публикации
                date_elem = card.find("span", class_=re.compile(r"date|time|ago")) or \
                            card.find(string=re.compile(r"\d{1,2}\s*(?:мин|час|дн|недел)\w*\s*назад", re.IGNORECASE))
                published_date = date_elem.text.strip() if date_elem else ""

                apt = Apartment(
                    source="n1",
                    url=apt_url,
                    price=price,
                    area=area,
                    address="Новосибирск",
                    floor=1,
                    total_floors=10,
                    rooms=parse_rooms(description),
                    bathrooms=parse_bathrooms(description),
                    year=None,
                    has_balcony=has_balcony(description),
                    condition=get_condition(description),
                    description=description[:200],
                    complex_name="",
                    published_date=published_date,
                )
                apartments.append(apt)
                
            except Exception as e:
                logger.error(f"N1.RU: ошибка парсинга карточки: {e}")
                continue

        logger.info(f"N1.RU: найдено {len(apartments)} объявлений")
        
    except Exception as e:
        logger.error(f"N1.RU: ошибка парсинга: {e}")
    
    await asyncio.sleep(REQUEST_DELAY)
    return apartments


async def parse_domclick(session: aiohttp.ClientSession) -> list[Apartment]:
    """Парсинг объявлений с Домклик (публичный доступ)"""
    apartments = []
    try:
        params = {
            "minArea": str(SEARCH_CONFIG["min_area"]),
            "maxPrice": str(SEARCH_CONFIG["max_price"]),
        }
        url = f"{SOURCES['domclick']}/search?deal_type=sale&category=living&offer_type=flat&{'&'.join(f'{k}={v}' for k, v in params.items())}"
        
        html = await fetch_page_with_retry(session, url, source="Домклик")
        if not html:
            logger.warning("Домклик: пропуск — требуется авторизация или сайт недоступен")
            return apartments

        soup = BeautifulSoup(html, "html.parser")
        
        cards = (
            soup.find_all("div", class_=re.compile(r"card|offer|item")) or
            soup.find_all("article", class_=re.compile(r"card|offer"))
        )
        
        for card in cards[:20]:
            try:
                link_elem = card.find("a", href=re.compile(r"/offer/"))
                if not link_elem:
                    continue
                apt_url = link_elem.get("href", "")
                if not apt_url.startswith("http"):
                    apt_url = SOURCES["domclick"] + apt_url

                price_elem = card.find(string=re.compile(r"\d+\s*₽"))
                price = parse_price(str(price_elem)) if price_elem else None
                if not price or price > SEARCH_CONFIG["max_price"]:
                    continue

                area_elem = card.find(string=re.compile(r"\d+\s*м²"))
                area = parse_area(str(area_elem)) if area_elem else None
                if not area or area < SEARCH_CONFIG["min_area"]:
                    continue

                desc_elem = (
                    card.find("p") or
                    card.find("div", class_=re.compile(r"desc|info"))
                )
                description = desc_elem.text.strip() if desc_elem else ""

                # Дата публикации
                date_elem = card.find("span", class_=re.compile(r"date|time|ago")) or \
                            card.find(string=re.compile(r"\d{1,2}\s*(?:мин|час|дн|недел)\w*\s*назад", re.IGNORECASE))
                published_date = date_elem.text.strip() if date_elem else ""

                apt = Apartment(
                    source="domclick",
                    url=apt_url,
                    price=price,
                    area=area,
                    address="Новосибирск",
                    floor=1,
                    total_floors=10,
                    rooms=parse_rooms(description),
                    bathrooms=parse_bathrooms(description),
                    year=None,
                    has_balcony=has_balcony(description),
                    condition=get_condition(description),
                    description=description[:200],
                    complex_name="",
                    published_date=published_date,
                )
                apartments.append(apt)
                
            except Exception as e:
                logger.error(f"Домклик: ошибка парсинга карточки: {e}")
                continue

        logger.info(f"Домклик: найдено {len(apartments)} объявлений")
        
    except Exception as e:
        logger.error(f"Домклик: ошибка парсинга: {e}")
    
    return apartments


async def search_apartments(use_cache: bool = True, max_age_days: int = 0) -> tuple[list[Apartment], list[str]]:
    """Поиск квартир по всем источникам с кешированием.

    Returns:
        (apartments, errors) — список квартир и список ошибок по источникам
    """
    cache_key = f"all_apartments_{max_age_days}"
    current_time = time.time()

    if use_cache and cache_key in _cache:
        cached_time, cached_data = _cache[cache_key]
        if current_time - cached_time < CACHE_TTL:
            logger.info(f"Используем кеш ({len(cached_data)} квартир)")
            return cached_data

    headers = {"User-Agent": get_random_ua()}

    errors: list[str] = []

    # === CIAN + N1.RU: всегда через Playwright ===
    all_apartments = []

    # CIAN: всегда через Playwright (HTTP заблокирован стабильно)
    try:
        pw_result = await parse_cian_playwright()
        if isinstance(pw_result, list) and pw_result:
            all_apartments.extend(pw_result)
            logger.info(f"Циан: получено {len(pw_result)} через Playwright")
        else:
            errors.append("⚠️ Циан: 0 объявлений")
    except Exception as e:
        errors.append(f"❌ Циан: {str(e)[:80]}")
        logger.error(f"Ошибка при парсинге Циан: {e}")

    # N1.RU: всегда через Playwright (HTTP заблокирован стабильно)
    try:
        pw_result = await parse_n1_playwright()
        if isinstance(pw_result, list) and pw_result:
            all_apartments.extend(pw_result)
            logger.info(f"N1.RU: получено {len(pw_result)} через Playwright")
        else:
            errors.append("⚠️ N1.RU: 0 объявлений")
    except Exception as e:
        errors.append(f"❌ N1.RU: {str(e)[:80]}")
        logger.error(f"Ошибка при парсинге N1.RU: {e}")

    # === Блок 2: Авито (UC non-headless, последовательно) ===
    _kill_chrome()
    avito_result = await parse_avito_playwright()
    if isinstance(avito_result, list) and avito_result:
        all_apartments.extend(avito_result)
        errors.append(f"ℹ️ Авито: получено {len(avito_result)} через UC")
    elif isinstance(avito_result, list) and not avito_result:
        errors.append("⚠️ Авито: 0 объявлений (UC)")
    elif isinstance(avito_result, Exception):
        errors.append(f"❌ Авито: {str(avito_result)[:80]}")

    # === Блок 3: Домклик (UC non-headless, последовательно) ===
    _kill_chrome()
    domclick_result = await parse_domclick_playwright()
    if isinstance(domclick_result, list) and domclick_result:
        all_apartments.extend(domclick_result)
        errors.append(f"ℹ️ Домклик: получено {len(domclick_result)} через UC")
    elif isinstance(domclick_result, list) and not domclick_result:
        errors.append("⚠️ Домклик: 0 объявлений (UC)")
    elif isinstance(domclick_result, Exception):
        errors.append(f"❌ Домклик: {str(domclick_result)[:80]}")

    _kill_chrome()

    decent_apartments = [apt for apt in all_apartments if is_decent_apartment(apt, max_age_days)]
    decent_apartments.sort(key=lambda x: x.price)

    _cache[cache_key] = (current_time, decent_apartments)

    logger.info(f"Всего найдено: {len(all_apartments)}, приличных: {len(decent_apartments)}")
    return decent_apartments, errors


async def get_last_apartments(count: int = 5, max_age_days: int = 0) -> tuple[list[Apartment], list[str]]:
    """Получить последние найденные квартиры"""
    apartments, errors = await search_apartments(use_cache=True, max_age_days=max_age_days)
    return apartments[:count], errors