"""
Пример использования парсера для поиска квартир
Этот скрипт можно запустить отдельно для тестирования парсинга
"""
import asyncio
import sys
import os

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import search_apartments, get_last_apartments


async def main():
    """Основная функция для тестирования парсинга"""
    print("🔍 Поиск квартир в Новосибирске...")
    print("=" * 50)
    
    try:
        # Поиск квартир
        apartments = await search_apartments(use_cache=False)
        
        if not apartments:
            print("😔 Квартиры не найдены")
            return
        
        print(f"\n✅ Найдено {len(apartments)} квартир:\n")
        
        # Вывод первых 10 результатов
        for i, apt in enumerate(apartments[:10], 1):
            print(f"{i}. {apt}")
            print("-" * 50)
        
        if len(apartments) > 10:
            print(f"\n... и ещё {len(apartments) - 10} квартир")
        
        # Тест получения последних результатов
        print("\n" + "=" * 50)
        print("📋 Тест получения последних результатов:")
        last_apartments = await get_last_apartments(3)
        
        for i, apt in enumerate(last_apartments, 1):
            print(f"\n{i}. {apt}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
