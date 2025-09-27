#!/usr/bin/env python3
"""
Скрипт для тестирования подключения к базе данных
"""

import os
import sys

def test_connection():
    """Тестирует подключение к базе данных"""
    try:
        # Добавляем текущую директорию в путь для импорта
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        from database.models import SessionLocal
        from sqlalchemy import text
        
        print("🔍 Тестирование подключения к базе данных...")
        print("-" * 50)
        
        # Показываем текущий DATABASE_URL
        from config.settings import DATABASE_URL
        print(f"📡 DATABASE_URL: {DATABASE_URL}")
        print()
        
        # Пытаемся подключиться
        db = SessionLocal()
        try:
            result = db.execute(text("SELECT 1 as test"))
            row = result.fetchone()
            
            if row and row[0] == 1:
                print("✅ Подключение к Supabase успешно!")
                print("✅ База данных доступна и отвечает на запросы")
                
                # Дополнительная проверка - показываем версию PostgreSQL
                try:
                    version_result = db.execute(text("SELECT version()"))
                    version = version_result.fetchone()[0]
                    print(f"📊 Версия PostgreSQL: {version.split(',')[0]}")
                except Exception as e:
                    print(f"⚠️  Не удалось получить версию PostgreSQL: {e}")
                    
            else:
                print("❌ Неожиданный результат запроса")
                
        except Exception as e:
            print(f"❌ Ошибка подключения: {e}")
            print("\n🔧 Возможные решения:")
            print("1. Проверьте правильность DATABASE_URL в .env файле")
            print("2. Убедитесь, что пароль правильный")
            print("3. Проверьте, что проект Supabase активен")
            print("4. Проверьте настройки безопасности в Supabase")
            return False
            
        finally:
            db.close()
            
        return True
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        print("🔧 Убедитесь, что все зависимости установлены:")
        print("pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

def main():
    print("🚀 Тест подключения к базе данных NewsBot")
    print("=" * 50)
    
    success = test_connection()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Тест завершен успешно! Бот готов к работе.")
    else:
        print("💥 Тест не пройден. Исправьте проблемы и попробуйте снова.")
        print("\n📖 Подробные инструкции в файле: ИСПРАВЛЕНИЕ_SUPABASE.md")

if __name__ == "__main__":
    main()