"""
Альтернативный парсер с Selenium для обхода антибот-защиты
Установка: pip install selenium webdriver-manager
"""
import logging
import re
import time
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False

from config import SEARCH_CONFIG, SOURCES

logger = logging.getLogger(__name__)


class SeleniumParser:
    """Парсер на основе Selenium для обхода антибот-защиты"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None
    
    def setup_driver(self) -> webdriver.Chrome:
        """Настройка WebDriver"""
        options = Options()
        
        if self.headless:
            options.add_argument("--headless=new")
        
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Отключаем определение автоматизации
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        if USE_WEBDRIVER_MANAGER:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)
        
        # Устанавливаем скрипт для скрытия автоматизации
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        return driver
    
    def parse_cian_selenium(self) -> list[dict]:
        """Парсинг Циан через Selenium"""
        apartments = []
        
        try:
            self.driver = self.setup_driver()
            
            # Формируем URL
            params = {
                "city": "2",
                "minarea": str(SEARCH_CONFIG["min_area"]),
                "maxprice": str(SEARCH_CONFIG["max_price"]),
            }
            url = f"{SOURCES['cian']}/cat.php?{'&'.join(f'{k}={v}' for k, v in params.items())}"
            
            self.driver.get(url)
            
            # Ждём загрузки карточек
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-name='CardComponent']"))
            )
            
            # Прокручиваем для загрузки всех карточек
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Извлекаем данные
            cards = self.driver.find_elements(By.CSS_SELECTOR, "[data-name='CardComponent']")
            
            for card in cards[:20]:
                try:
                    # Ссылка
                    link = card.find_element(By.CSS_SELECTOR, "a[data-name='CardLink']")
                    apt_url = link.get_attribute("href")
                    
                    # Цена
                    price_elem = card.find_element(By.CSS_SELECTOR, "[data-name='PriceInfo']")
                    price_text = price_elem.text
                    price = int(re.sub(r"[^\d]", "", price_text))
                    
                    if price > SEARCH_CONFIG["max_price"]:
                        continue
                    
                    # Площадь
                    area_elem = card.find_element(By.XPATH, ".//*[contains(text(), 'м²')]")
                    area_text = area_elem.text
                    area = float(re.search(r"(\d+(?:[.,]\d+)?)", area_text).group(1).replace(",", "."))
                    
                    if area < SEARCH_CONFIG["min_area"]:
                        continue
                    
                    # Этаж
                    floor_elem = card.find_element(By.XPATH, ".//*[matches(text(), '\\d+/\\d+')]")
                    floor_text = floor_elem.text
                    floor_match = re.search(r"(\d+)/(\d+)", floor_text)
                    floor = int(floor_match.group(1))
                    total_floors = int(floor_match.group(2))
                    
                    # Описание
                    desc_elem = card.find_element(By.CSS_SELECTOR, "p[data-name='Description']")
                    description = desc_elem.text
                    
                    apartments.append({
                        "source": "cian",
                        "url": apt_url,
                        "price": price,
                        "area": area,
                        "floor": floor,
                        "total_floors": total_floors,
                        "description": description[:200],
                    })
                    
                except Exception as e:
                    logger.error(f"Ошибка парсинга карточки: {e}")
                    continue
            
            logger.info(f"Сelenium Циан: найдено {len(apartments)} объявлений")
            
        except Exception as e:
            logger.error(f"Ошибка Selenium парсинга Циан: {e}")
        
        finally:
            if self.driver:
                self.driver.quit()
        
        return apartments
    
    def parse_avito_selenium(self) -> list[dict]:
        """Парсинг Авито через Selenium"""
        apartments = []
        
        try:
            self.driver = self.setup_driver()
            
            url = f"{SOURCES['avito']}/novosibirsk/kvartiry/prodam-ASgBAgICAUSSA8YQ"
            
            self.driver.get(url)
            
            # Ждём загрузки карточек
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-marker='item']"))
            )
            
            # Прокручиваем
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            cards = self.driver.find_elements(By.CSS_SELECTOR, "[data-marker='item']")
            
            for card in cards[:20]:
                try:
                    # Ссылка
                    link = card.find_element(By.CSS_SELECTOR, "a[itemprop='url']")
                    apt_url = SOURCES["avito"] + link.get_attribute("href")
                    
                    # Цена
                    price_elem = card.find_element(By.CSS_SELECTOR, "meta[itemprop='price']")
                    price = int(price_elem.get_attribute("content"))
                    
                    if price > SEARCH_CONFIG["max_price"]:
                        continue
                    
                    # Название
                    title_elem = card.find_element(By.CSS_SELECTOR, "h2[itemprop='name']")
                    title = title_elem.text
                    
                    # Площадь из названия
                    area_match = re.search(r"(\d+(?:[.,]\d+)?)\s*м²", title)
                    if not area_match:
                        continue
                    area = float(area_match.group(1).replace(",", "."))
                    
                    if area < SEARCH_CONFIG["min_area"]:
                        continue
                    
                    apartments.append({
                        "source": "avito",
                        "url": apt_url,
                        "price": price,
                        "area": area,
                        "floor": 1,
                        "total_floors": 10,
                        "description": title[:200],
                    })
                    
                except Exception as e:
                    logger.error(f"Ошибка парсинга карточки Авито: {e}")
                    continue
            
            logger.info(f"Сelenium Авито: найдено {len(apartments)} объявлений")
            
        except Exception as e:
            logger.error(f"Ошибка Selenium парсинга Авито: {e}")
        
        finally:
            if self.driver:
                self.driver.quit()
        
        return apartments


def get_selenium_parser() -> SeleniumParser:
    """Получение экземпляра Selenium парсера"""
    return SeleniumParser(headless=True)
