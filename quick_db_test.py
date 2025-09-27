#!/usr/bin/env python3
"""
Быстрый тест подключения к базе данных с таймаутом
"""

import os
import signal
import sys
from contextlib import contextmanager

@contextmanager
def timeout(duration):
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Операция прервана через {duration} секунд")
    
    # Устанавливаем таймаут
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(duration)
    
    try:
        yield
    finally:
        # Отменяем таймаут
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

def quick_test():
    print("🚀 Быстрый тест подключения к Supabase")
    print("=" * 40)
    
    try:
        # Добавляем текущую директорию в путь
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        from database.models import SessionLocal
        from sqlalchemy import text
        
        print("📡 Попытка подключения к базе данных...")
        print("⏱️  Таймаут: 10 секунд")
        
        with timeout(10):  # 10 секунд таймаут
            db = SessionLocal()
            try:
                result = db.execute(text("SELECT 1 as test"))
                row = result.fetchone()
                
                if row and row[0] == 1:
                    print("✅ Подключение успешно!")
                    print("✅ База данных отвечает")
                    return True
                else:
                    print("❌ Неожиданный результат запроса")
                    return False
                    
            except Exception as e:
                print(f"❌ Ошибка подключения: {e}")
                return False
            finally:
                db.close()
                
    except TimeoutError as e:
        print(f"⏰ {e}")
        print("💡 Возможные причины:")
        print("   - Проект Supabase приостановлен")
        print("   - Проблемы с сетью")
        print("   - Неправильные учетные данные")
        return False
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

if __name__ == "__main__":
    success = quick_test()
    
    print("\n" + "=" * 40)
    if success:
        print("🎉 Тест пройден! Supabase работает.")
    else:
        print("💥 Тест не пройден. Проверьте настройки.")
        print("\n📖 Рекомендации:")
        print("1. Проверьте статус проекта в Supabase")
        print("2. Убедитесь, что проект не приостановлен")
        print("3. Проверьте правильность пароля")
        print("4. Попробуйте создать новый проект Supabase")
