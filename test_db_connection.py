#!/usr/bin/env python3
"""
Скрипт для тестирования подключения к базе данных
"""

import os
from dotenv import load_dotenv

load_dotenv()

def test_database_connection():
    """Тестирует подключение к базе данных"""
    try:
        from database.models import SessionLocal, engine
        from sqlalchemy import text
        
        print("🔄 Тестирование подключения к базе данных...")
        print(f"📍 DATABASE_URL: {os.getenv('DATABASE_URL', 'Не задан')[:50]}...")
        
        # Тест подключения
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 as test"))
            row = result.fetchone()
            if row and row[0] == 1:
                print("✅ Подключение к базе данных успешно!")
            else:
                print("❌ Неожиданный результат запроса")
                return False
                
        # Тест сессии
        db = SessionLocal()
        try:
            result = db.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"📊 Версия PostgreSQL: {version}")
            print("✅ Сессия базы данных работает!")
            return True
        finally:
            db.close()
            
    except Exception as e:
        print(f"❌ Ошибка подключения к базе данных: {e}")
        print("\n🔧 Возможные решения:")
        print("1. Проверьте DATABASE_URL в .env файле")
        print("2. Убедитесь, что установлен psycopg2-binary: pip install psycopg2-binary")
        print("3. Проверьте, что Supabase проект активен")
        print("4. Убедитесь, что IP не заблокирован в настройках Supabase")
        return False

def test_tables_creation():
    """Тестирует создание таблиц"""
    try:
        from database.models import Base, engine
        
        print("\n🔄 Тестирование создания таблиц...")
        Base.metadata.create_all(engine)
        print("✅ Таблицы успешно созданы/проверены!")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания таблиц: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Тестирование базы данных NewsBot")
    print("=" * 50)
    
    connection_ok = test_database_connection()
    if connection_ok:
        tables_ok = test_tables_creation()
        
        if tables_ok:
            print("\n🎉 Все тесты пройдены! База данных готова к работе.")
        else:
            print("\n💥 Проблемы с созданием таблиц.")
    else:
        print("\n💥 Проблемы с подключением к базе данных.")
