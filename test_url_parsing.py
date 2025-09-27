#!/usr/bin/env python3
"""
Скрипт для тестирования парсинга URL подключения
"""

import urllib.parse
from urllib.parse import urlparse

def test_url_parsing():
    print("🔍 Тестирование парсинга URL подключения")
    print("=" * 50)
    
    # Читаем текущий DATABASE_URL
    try:
        with open('.env', 'r') as f:
            content = f.read()
            
        for line in content.strip().split('\n'):
            if line.startswith('DATABASE_URL='):
                database_url = line.split('=', 1)[1]
                break
        else:
            print("❌ DATABASE_URL не найден в .env файле")
            return
            
        print(f"📡 Текущий DATABASE_URL: {database_url}")
        print()
        
        # Парсим URL
        try:
            parsed = urlparse(database_url)
            print("📊 Парсинг URL:")
            print(f"  Схема: {parsed.scheme}")
            print(f"  Пользователь: {parsed.username}")
            print(f"  Пароль: {parsed.password}")
            print(f"  Хост: {parsed.hostname}")
            print(f"  Порт: {parsed.port}")
            print(f"  База данных: {parsed.path[1:]}")
            print()
            
            # Проверяем компоненты
            if not parsed.username:
                print("❌ Проблема: отсутствует username")
            if not parsed.password:
                print("❌ Проблема: отсутствует password")
            if not parsed.hostname:
                print("❌ Проблема: отсутствует hostname")
            elif parsed.hostname.startswith('.'):
                print("❌ Проблема: hostname начинается с точки")
            if not parsed.port:
                print("❌ Проблема: отсутствует port")
            if not parsed.path or parsed.path == '/':
                print("❌ Проблема: отсутствует database name")
                
        except Exception as e:
            print(f"❌ Ошибка парсинга URL: {e}")
            
    except FileNotFoundError:
        print("❌ Файл .env не найден")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    test_url_parsing()
