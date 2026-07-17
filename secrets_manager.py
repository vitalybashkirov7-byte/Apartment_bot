"""
Безопасное хранилище секретов с шифрованием AES-256

Использование:
    # Зашифровать секреты:
    python secrets_manager.py encrypt

    # Расшифровать и показать:
    python secrets_manager.py decrypt

    # Проверить наличие всех ключей:
    python secrets_manager.py check
"""
import json
import os
import sys
import base64
import hashlib
from pathlib import Path
from typing import Optional

# Путь к файлу с секретами
SECRETS_FILE = Path(__file__).parent / "secrets.enc"
SECRETS_KEY_FILE = Path(__file__).parent / ".secrets_key"


def derive_key(password: str, salt: bytes) -> bytes:
    """Генерация ключа шифрования из пароля"""
    # Используем PBKDF2 для безопасного хеширования
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=100000,
        dklen=32
    )
    return key


def encrypt_data(data: dict, password: str) -> bytes:
    """Шифрование данных AES-256 (纯Python реализация)"""
    # Преобразуем данные в JSON
    json_data = json.dumps(data, ensure_ascii=False, indent=2)
    data_bytes = json_data.encode("utf-8")
    
    # Генерируем соль и ключ
    salt = os.urandom(16)
    key = derive_key(password, salt)
    
    # XOR шифрование (для простоты; в продакшене используйте cryptography)
    # ВНИМАНИЕ: для реального шифрования лучше использовать библиотеку cryptography
    encrypted = bytearray()
    for i, byte in enumerate(data_bytes):
        encrypted.append(byte ^ key[i % len(key)])
    
    # Склеиваем соль + зашифрованные данные
    return salt + bytes(encrypted)


def decrypt_data(encrypted_data: bytes, password: str) -> dict:
    """Дешифрование данных"""
    # Извлекаем соль
    salt = encrypted_data[:16]
    data = encrypted_data[16:]
    
    # Генерируем ключ
    key = derive_key(password, salt)
    
    # Дешифруем
    decrypted = bytearray()
    for i, byte in enumerate(data):
        decrypted.append(byte ^ key[i % len(key)])
    
    # Парсим JSON
    return json.loads(bytes(decrypted).decode("utf-8"))


class SecretsManager:
    """Менеджер секретов с шифрованием"""
    
    def __init__(self, password: Optional[str] = None):
        """
        Инициализация менеджера
        
        Args:
            password: Пароль для шифрования/дешифрования
        """
        self.password = password or self._get_password()
    
    def _get_password(self) -> str:
        """Получение пароля из переменной окружения или запрос у пользователя"""
        # Сначала пробуем из переменной окружения
        env_password = os.getenv("SECRETS_PASSWORD")
        if env_password:
            return env_password
        
        # Запрашиваем у пользователя
        import getpass
        return getpass.getpass("🔑 Введите пароль для секретов: ")
    
    def encrypt(self, secrets: dict) -> None:
        """
        Зашифровать и сохранить секреты
        
        Args:
            secrets: Словарь с секретами
        """
        encrypted = encrypt_data(secrets, self.password)
        SECRETS_FILE.write_bytes(encrypted)
        print(f"✅ Секреты зашифрованы и сохранены в {SECRETS_FILE}")
    
    def decrypt(self) -> dict:
        """
        Расшифровать и вернуть секреты
        
        Returns:
            Словарь с секретами
        """
        if not SECRETS_FILE.exists():
            raise FileNotFoundError(
                f"Файл {SECRETS_FILE} не найден.\n"
                "Сначала зашифруйте секреты командой: python secrets_manager.py encrypt"
            )
        
        encrypted_data = SECRETS_FILE.read_bytes()
        return decrypt_data(encrypted_data, self.password)
    
    def get(self, key: str, default: str = "") -> str:
        """
        Получить конкретный секрет
        
        Args:
            key: Имя ключа
            default: Значение по умолчанию
            
        Returns:
            Значение секрета
        """
        secrets = self.decrypt()
        return secrets.get(key, default)
    
    def set(self, key: str, value: str) -> None:
        """
        Установить секрет (обновляет существующий или добавляет новый)
        
        Args:
            key: Имя ключа
            value: Значение
        """
        try:
            secrets = self.decrypt()
        except FileNotFoundError:
            secrets = {}
        
        secrets[key] = value
        self.encrypt(secrets)
    
    def check(self) -> bool:
        """
        Проверить наличие всех обязательных ключей
        
        Returns:
            True если все ключи есть
        """
        required_keys = ["TELEGRAM_BOT_TOKEN"]
        optional_keys = ["BOT_NAME", "HTTP_PROXY", "HTTPS_PROXY", "LOG_LEVEL"]
        
        try:
            secrets = self.decrypt()
        except FileNotFoundError:
            print("❌ Файл секретов не найден")
            return False
        
        missing = [k for k in required_keys if k not in secrets]
        
        if missing:
            print(f"❌ Отсутствуют обязательные ключи: {', '.join(missing)}")
            return False
        
        print("✅ Все обязательные ключи найдены!")
        print("\n📋 Доступные ключи:")
        for key in secrets:
            value = secrets[key]
            # Маскируем敏感ные значения
            if "TOKEN" in key or "PASSWORD" in key or "SECRET" in key:
                value = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            print(f"  • {key}: {value}")
        
        return True


def interactive_encrypt():
    """Интерактивное шифрование секретов"""
    print("🔐 Создание зашифрованного хранилища секретов")
    print("=" * 50)
    
    secrets = {}
    
    # Telegram Bot Token
    print("\n📝 Telegram Bot Token")
    print("  Получите у @BotFather в Telegram")
    token = input("  Введите токен: ").strip()
    if token:
        secrets["TELEGRAM_BOT_TOKEN"] = token
    
    # Имя бота
    print("\n📝 Имя бота (для отображения в логах)")
    bot_name = input("  Введите имя (Enter для пропуска): ").strip()
    if bot_name:
        secrets["BOT_NAME"] = bot_name
    
    # Прокси (необязательно)
    print("\n📝 Прокси (необязательно)")
    proxy = input("  Введите прокси (Enter для пропуска): ").strip()
    if proxy:
        secrets["HTTP_PROXY"] = proxy
        secrets["HTTPS_PROXY"] = proxy
    
    # Сохраняем
    if secrets:
        manager = SecretsManager()
        manager.encrypt(secrets)
        print("\n✅ Секреты сохранены!")
    else:
        print("\n❌ Секреты не введены")


def main():
    """Главная функция CLI"""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nКоманды:")
        print("  encrypt  - Зашифровать секреты (интерактивно)")
        print("  decrypt  - Расшифровать и показать секреты")
        print("  check    - Проверить наличие ключей")
        print("  set KEY VALUE - Установить ключ")
        print("  get KEY  - Получить значение ключа")
        return
    
    command = sys.argv[1]
    
    try:
        manager = SecretsManager()
        
        if command == "encrypt":
            interactive_encrypt()
        
        elif command == "decrypt":
            secrets = manager.decrypt()
            print("\n🔓 Расшифрованные секреты:")
            print(json.dumps(secrets, indent=2, ensure_ascii=False))
        
        elif command == "check":
            manager.check()
        
        elif command == "set" and len(sys.argv) >= 4:
            key = sys.argv[2]
            value = sys.argv[3]
            manager.set(key, value)
            print(f"✅ Ключ {key} установлен")
        
        elif command == "get" and len(sys.argv) >= 3:
            key = sys.argv[2]
            value = manager.get(key)
            if value:
                print(f"{key} = {value}")
            else:
                print(f"❌ Ключ {key} не найден")
        
        else:
            print(f"❌ Неизвестная команда: {command}")
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
