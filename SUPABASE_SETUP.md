# Настройка Supabase для NewsBot

## 1. Создание проекта в Supabase

1. Перейдите на [supabase.com](https://supabase.com)
2. Создайте новый проект
3. Дождитесь завершения создания базы данных

## 2. Получение строки подключения

1. В панели Supabase перейдите в **Settings** → **Database**
2. Найдите секцию **Connection string**
3. Скопируйте строку подключения (URI)
4. Замените `[YOUR-PASSWORD]` на ваш пароль базы данных

Пример строки подключения:
```
postgresql://postgres:[YOUR-PASSWORD]@db.abcdefghijklmnop.supabase.co:5432/postgres
```

## 3. Настройка переменных окружения

Создайте файл `.env` в корневой папке проекта:

```env
# Telegram Bot
BOT_TOKEN=your_bot_token_here
ADMIN_IDS=123456789,987654321

# Supabase Database
DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
```

## 4. Установка зависимостей

Убедитесь, что установлен драйвер PostgreSQL:

```bash
pip install psycopg2-binary
```

Или обновите requirements.txt и установите все зависимости:

```bash
pip install -r requirements.txt
```

## 5. Создание таблиц

При первом запуске бота таблицы будут созданы автоматически благодаря SQLAlchemy.

Если нужно создать таблицы вручную, выполните:

```python
from database.models import Base, engine
Base.metadata.create_all(engine)
```

## 6. Проверка подключения

Для проверки подключения к базе данных:

```python
from database.models import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    result = db.execute(text("SELECT 1"))
    print("✅ Подключение к Supabase успешно!")
except Exception as e:
    print(f"❌ Ошибка подключения: {e}")
finally:
    db.close()
```

## Возможные проблемы

### Ошибка "psycopg2 not found"
```bash
pip install psycopg2-binary
```

### Ошибка подключения
- Проверьте правильность DATABASE_URL
- Убедитесь, что пароль содержит только безопасные символы
- Проверьте, что IP адрес не заблокирован в Supabase

### Ошибка "relation does not exist"
Таблицы создаются автоматически при первом запуске. Если проблема сохраняется, проверьте права доступа к базе данных.

