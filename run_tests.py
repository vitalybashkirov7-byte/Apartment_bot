"""
Запуск тестов
python run_tests.py
"""
import os
import sys
import unittest

# Загружаем токен из системной переменной Windows
if "TELEGRAM_BOT_TOKEN" not in os.environ:
    import subprocess
    result = subprocess.run(
        ["powershell", "-Command", "[Environment]::GetEnvironmentVariable('TELEGRAM_BOT_TOKEN','User')"],
        capture_output=True, text=True
    )
    token = result.stdout.strip()
    if token:
        os.environ["TELEGRAM_BOT_TOKEN"] = token

# Добавляем корень проекта в путь
sys.path.insert(0, ".")

# Загружаем тесты
loader = unittest.TestLoader()
suite = unittest.TestSuite()

# Добавляем тесты
suite.addTests(loader.discover("tests", pattern="test_*.py"))

# Запуск
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)

# Возврат кода ошибки
sys.exit(0 if result.wasSuccessful() else 1)
