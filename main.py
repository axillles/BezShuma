import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from config.settings import BOT_TOKEN, DATABASE_URL
from bot.handlers import router
from admin.panel import admin_router
from core.scheduler import Scheduler

# Optional: Postgres advisory lock
from sqlalchemy import text
try:
    from database.models import engine as db_engine
except Exception:  # engine may fail only if env is broken; we handle at runtime
    db_engine = None

# Optional: file lock fallback for non-Postgres
try:
    import fcntl  # type: ignore
except Exception:
    fcntl = None  # on Windows or restricted env, we skip file locking

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

_POSTGRES_LOCK_KEY = 210987654321  # 64-bit advisory lock key (constant per app)
_file_lock_handle = None
_pg_lock_connection = None


def _acquire_singleton_lock() -> bool:
    global _file_lock_handle, _pg_lock_connection

    url = (DATABASE_URL or "").lower()

    # Prefer PostgreSQL advisory lock when using Postgres
    if url.startswith("postgresql") and db_engine is not None:
        try:
            conn = db_engine.connect()
            # Try to obtain session-level advisory lock; keep connection open while running
            acquired = conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": _POSTGRES_LOCK_KEY}).scalar()
            if acquired:
                _pg_lock_connection = conn
                logger.info("Получен advisory lock в PostgreSQL (singleton запущен)")
                return True
            else:
                conn.close()
                logger.error("Не удалось получить advisory lock в PostgreSQL — уже запущен другой инстанс")
                return False
        except Exception as e:
            logger.warning(f"Не удалось установить advisory lock в PostgreSQL: {e}. Перехожу к файловому lock.")
            # fallthrough to file lock

    # File lock fallback (Unix-like only)
    if fcntl is not None:
        try:
            lock_path = "/tmp/newsbot.singleton.lock"
            _file_lock_handle = open(lock_path, "w+")
            fcntl.flock(_file_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            _file_lock_handle.write(str(os.getpid()))
            _file_lock_handle.flush()
            logger.info("Получен файловый lock (singleton запущен)")
            return True
        except Exception as e:
            logger.error(f"Не удалось получить файловый lock — вероятно, уже запущен другой инстанс: {e}")
            # Ensure handle is closed if partially opened
            try:
                if _file_lock_handle:
                    _file_lock_handle.close()
            finally:
                _file_lock_handle = None
            return False

    # If no locking mechanism available, proceed (best-effort) — but warn
    logger.warning("Механизм блокировки недоступен. Возможен конфликт нескольких инстансов.")
    return True


def _release_singleton_lock() -> None:
    global _file_lock_handle, _pg_lock_connection

    # Release Postgres advisory lock if held
    if _pg_lock_connection is not None:
        try:
            _pg_lock_connection.execute(text("select pg_advisory_unlock(:k)"), {"k": _POSTGRES_LOCK_KEY})
        except Exception:
            pass
        try:
            _pg_lock_connection.close()
        except Exception:
            pass
        _pg_lock_connection = None

    # Release file lock if held
    if _file_lock_handle is not None and fcntl is not None:
        try:
            fcntl.flock(_file_lock_handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            _file_lock_handle.close()
        except Exception:
            pass
        _file_lock_handle = None


async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command='/start', description='🚀 Запустить/перезапустить бота'),
        BotCommand(command='/my_channels', description='📊 Мои каналы'),
        BotCommand(command='/add_channel', description='➕ Добавить новый канал'),
        BotCommand(command='/admin', description='👑 Панель администратора')
    ]
    await bot.set_my_commands(main_menu_commands)


async def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN не найден! Проверьте ваш .env файл.")
        return

    if not _acquire_singleton_lock():
        # Exit immediately to avoid Telegram getUpdates conflict
        logger.error("Завершаю работу: обнаружен параллельный инстанс.")
        return

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(router)
    dp.include_router(admin_router)

    await set_main_menu(bot)

    scheduler = Scheduler(bot)
    scheduler.start()

    try:
        logger.info("Бот запущен")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.stop()
        await bot.session.close()
        _release_singleton_lock()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка по команде пользователя")