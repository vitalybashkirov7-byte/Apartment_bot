"""
Продвинутое хранилище секретов с AES-256 шифрованием

Требования:
    pip install cryptography

Использование:
    # Зашифровать секреты:
    python secrets_crypto.py encrypt

    # Расшифровать:
    python secrets_crypto.py decrypt

    # Загрузить секреты в переменные окружения:
    python secrets_crypto.py load
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    print("⚠️  Библиотека cryptography не установлена")
    print("   Установите: pip install cryptography")
    print("   Используем простой вариант...")

# Путь к файлу с секретами
SECRETS_FILE = Path(__file__).parent / "secrets.encrypted"


def generate_key_from_password(password: str, salt: bytes) -> bytes:
    """Генерация ключа из пароля через PBKDF2"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,  # OWASP рекомендация
    )
    key = kdf.derive(password.encode())
    return key


class CryptoSecretsManager:
    """Менеджер секретов с AES-256 шифрованием"""
    
    def __init__(self, password: Optional[str] = None):
        if not HAS_CRYPTOGRAPHY:
            raise ImportError(
                "Для шифрования установите cryptography:\n"
                "pip install cryptography"
            )
        
        self.password = password or self._get_password()
    
    def _get_password(self) -> str:
        """Получение пароля"""
        env_password = os.getenv("SECRETS_PASSWORD")
        if env_password:
            return env_password
        
        import getpass
        return getpass.getpass("🔑 Введите пароль для шифрования: ")
    
    def encrypt(self, secrets: dict) -> None:
        """Зашифровать и сохранить секреты"""
        # Сериализуем данные
        json_data = json.dumps(secrets, ensure_ascii=False).encode()
        
        # Генерируем соль и ключ
        salt = os.urandom(16)
        key = generate_key_from_password(self.password, salt)
        
        # Шифруем
        fernet = Fernet(base64.urlsafe_b64encode(key))
        encrypted = fernet.encrypt(json_data)
        
        # Сохраняем: соль + зашифрованные данные
        SECRETS_FILE.write_bytes(salt + encrypted)
        print(f"✅ Секреты зашифрованы: {SECRETS_FILE}")
    
    def decrypt(self) -> dict:
        """Расшифровать и вернуть секреты"""
        if not SECRETS_FILE.exists():
            raise FileNotFoundError(f"Файл {SECRETS_FILE} не найден")
        
        # Читаем данные
        data = SECRETS_FILE.read_bytes()
        salt = data[:16]
        encrypted = data[16:]
        
        # Генерируем ключ и расшифровываем
        key = generate_key_from_password(self.password, salt)
        fernet = Fernet(base64.urlsafe_b64encode(key))
        decrypted = fernet.decrypt(encrypted)
        
        return json.loads(decrypted.decode())
    
    def get(self, key: str, default: str = "") -> str:
        """Получить значение ключа"""
        secrets = self.decrypt()
        return secrets.get(key, default)
    
    def set(self, key: str, value: str) -> None:
        """Установить значение ключа"""
        try:
            secrets = self.decrypt()
        except FileNotFoundError:
            secrets = {}
        
        secrets[key] = value
        self.encrypt(secrets)
    
    def check(self) -> bool:
        """Проверить наличие всех ключей"""
        required = ["TELEGRAM_BOT_TOKEN"]
        optional = ["BOT_NAME", "HTTP_PROXY", "HTTPS_PROXY"]
        
        try:
            secrets = self.decrypt()
        except FileNotFoundError:
            print("❌ Файл секретов не найден")
            return False
        
        missing = [k for k in required if k not in secrets]
        
        if missing:
            print(f"❌ Отсутствуют: {', '.join(missing)}")
            return False
        
        print("✅ Все ключи найдены!")
        print("\n📋 Секреты:")
        for key, value in secrets.items():
            # Маскируем敏感ные данные
            if any(s in key for s in ["TOKEN", "PASSWORD", "SECRET", "KEY"]):
                if len(value) > 8:
                    display = value[:4] + "..." + value[-4:]
                else:
                    display = "****"
            else:
                display = value
            print(f"  {key}: {display}")
        
        return True
    
    def load_to_env(self) -> None:
        """Загрузить секреты в переменные окружения"""
        secrets = self.decrypt()
        for key, value in secrets.items():
            os.environ[key] = value
        print(f"✅ Загружено {len(secrets)} секретов в окружение")


def interactive_setup():
    """Интерактивная настройка секретов"""
    print("🔐 Настройка зашифрованного хранилища секретов")
    print("=" * 55)
    
    secrets = {}
    
    # Telegram Bot Token
    print("\n📝 Telegram Bot Token")
    print("   1. Откройте Telegram")
    print("   2. Найдите @BotFather")
    print("   3. Отправьте /newbot")
    print("   4. Скопируйте токен")
    token = input("\n   Токен: ").strip()
    if token:
        secrets["TELEGRAM_BOT_TOKEN"] = token
    
    # Имя бота
    print("\n📝 Имя бота (отображается в логах)")
    bot_name = input("   Имя (Enter = пропустить): ").strip()
    if bot_name:
        secrets["BOT_NAME"] = bot_name
    
    # Прокси (необязательно)
    print("\n📝 HTTP Прокси (необязательно)")
    print("   Пример: http://user:pass@proxy:port")
    proxy = input("   Прокси (Enter = пропустить): ").strip()
    if proxy:
        secrets["HTTP_PROXY"] = proxy
        secrets["HTTPS_PROXY"] = proxy
    
    if not secrets:
        print("\n❌ Секреты не введены")
        return
    
    # Сохраняем
    manager = CryptoSecretsManager()
    manager.encrypt(secrets)
    
    print("\n" + "=" * 55)
    print("✅ Готово! Теперь вы можете:")
    print("   python secrets_crypto.py check   - проверить ключи")
    print("   python secrets_crypto.py decrypt  - посмотреть секреты")
    print("   python secrets_crypto.py load     - загрузить в окружение")


def main():
    """CLI интерфейс"""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nКоманды:")
        print("  encrypt       - Создать/обновить зашифрованные секреты")
        print("  decrypt       - Показать расшифрованные секреты")
        print("  check         - Проверить наличие ключей")
        print("  load          - Загрузить секреты в переменные окружения")
        print("  set KEY VALUE - Установить ключ")
        print("  get KEY       - Получить значение ключа")
        return
    
    command = sys.argv[1]
    
    try:
        manager = CryptoSecretsManager()
        
        if command == "encrypt":
            interactive_setup()
        
        elif command == "decrypt":
            secrets = manager.decrypt()
            print("\n🔓 Секреты:")
            print(json.dumps(secrets, indent=2, ensure_ascii=False))
        
        elif command == "check":
            manager.check()
        
        elif command == "load":
            manager.load_to_env()
        
        elif command == "set" and len(sys.argv) >= 4:
            manager.set(sys.argv[2], sys.argv[3])
            print(f"✅ {sys.argv[2]} установлен")
        
        elif command == "get" and len(sys.argv) >= 3:
            value = manager.get(sys.argv[2])
            print(f"{sys.argv[2]} = {value}" if value else f"❌ Ключ не найден")
        
        else:
            print(f"❌ Неизвестная команда: {command}")
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
