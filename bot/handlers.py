from aiogram import Router, F, Bot
from utils.helpers import safe_edit_text
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.keyboards import Keyboards
from database.crud import *
from database import crud
from database.models import SessionLocal, Channel, RSSSource, Post
from core.publisher import Publisher
from core.ai_processor import AIProcessor
from config.settings import ADMIN_IDS
from datetime import datetime, timedelta
import random

router = Router()
keyboards = Keyboards()


class ChannelStates(StatesGroup):
    waiting_channel_id = State()
    waiting_channel_topic = State()
    waiting_rss_url = State()
    waiting_rss_search = State()
    waiting_post_content = State()
    waiting_ai_prompt = State()
    editing_post = State()
    waiting_manual_rss = State()


@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    await state.clear()
    db = SessionLocal()
    user = get_or_create_user(db, message.from_user.id, message.from_user.username)

    if message.from_user.id in ADMIN_IDS and not user.is_admin:
        user.is_admin = True
        db.commit()

    db.close()

    await message.answer(
        "👋 Добро пожаловать в Channel Manager Bot!\n\n"
        "Я помогу автоматизировать ведение ваших телеграм-каналов.",
        reply_markup=keyboards.main_admin_menu()
    )


@router.callback_query(F.data == "back_main")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_text(callback.message, "Главное меню:", reply_markup=keyboards.main_admin_menu())


@router.message(Command("my_channels"))
@router.callback_query(F.data == "my_channels")
async def show_channels(event: Message | CallbackQuery):
    db = SessionLocal()
    user = get_or_create_user(db, event.from_user.id, event.from_user.username)
    channels = get_user_channels(db, user.id)
    db.close()

    text = "У вас пока нет каналов. Хотите добавить первый?" if not channels else "📊 Ваши каналы:"

    keyboard = []
    if channels:
        for channel in channels:
            status = "🟢" if channel.is_active else "🔴"
            keyboard.append([InlineKeyboardButton(
                text=f"{status} {channel.channel_name}",
                callback_data=f"channel_{channel.id}"
            )])

    keyboard.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")])
    if isinstance(event, CallbackQuery):
        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    if isinstance(event, Message):
        await event.answer(text, reply_markup=reply_markup)
    else:
        await safe_edit_text(event.message, text, reply_markup=reply_markup)


@router.message(Command("add_channel"))
@router.callback_query(F.data == "add_channel")
async def add_channel_start(event: Message | CallbackQuery, state: FSMContext):
    text = (
        "<b>Шаг 1: Добавление канала</b>\n\n"
        "1. Добавьте этого бота в администраторы вашего канала с правом на публикацию постов.\n"
        "2. Пришлите сюда <code>@username</code>, ссылку <code>https://t.me/channel</code> или просто перешлите любое сообщение из него."
    )
    if isinstance(event, Message):
        await event.answer(text)
    else:
        await safe_edit_text(event.message, text)
    await state.set_state(ChannelStates.waiting_channel_id)


@router.message(StateFilter(ChannelStates.waiting_channel_id))
async def process_channel_id(message: Message, state: FSMContext, bot: Bot):
    channel_id = None
    channel_name = None
    channel_input = None

    if message.forward_from_chat:
        channel_id = str(message.forward_from_chat.id)
        channel_name = message.forward_from_chat.title
    elif message.text:
        if message.text.startswith("@"):
            channel_input = message.text
        elif message.text.startswith("https://t.me/"):
            channel_input = f"@{message.text.split('/')[-1]}"

        if channel_input:
            try:
                chat = await bot.get_chat(channel_input)
                channel_id = str(chat.id)
                channel_name = chat.title
            except Exception:
                await message.answer(
                    "Не удалось найти канал. Убедитесь, что бот добавлен в него с правами администратора, и попробуйте снова.")
                return
        else:
            await message.answer(
                "Неверный формат. Пожалуйста, перешлите сообщение из канала или отправьте его @username / ссылку.")
            return
    else:
        await message.answer(
            "Неверный формат. Пожалуйста, перешлите сообщение из канала или отправьте его @username / ссылку.")
        return

    if channel_id:
        db = SessionLocal()
        existing_channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
        db.close()
        if existing_channel:
            await message.answer(
                f"Канал '{channel_name}' уже добавлен в систему. Вы можете управлять им через меню /my_channels.")
            await state.clear()
            return

        await state.update_data(channel_id=channel_id, channel_name=channel_name)
        await message.answer(
            "Отлично! Теперь введите основную тему канала (например: 'Новости IT', 'Криптовалюты', 'Маркетинг'):")
        await state.set_state(ChannelStates.waiting_channel_topic)


@router.message(StateFilter(ChannelStates.waiting_channel_topic))
async def process_channel_topic(message: Message, state: FSMContext):
    data = await state.get_data()
    db = SessionLocal()
    user = get_or_create_user(db, message.from_user.id, message.from_user.username)

    channel = create_channel(
        db, user.id, data['channel_id'],
        data['channel_name'], message.text
    )
    db.close()

    await state.clear()

    await message.answer(
        f"✅ Канал '{data['channel_name']}' успешно добавлен!\n\n"
        "Теперь необходимо добавить источники новостей (RSS-ленты).",
        reply_markup=keyboards.channel_menu(channel.id)
    )


@router.callback_query(F.data.startswith("channel_"))
async def channel_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    channel_id = int(callback.data.split("_")[1])

    db = SessionLocal()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    db.close()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        return

    status = "активен 🟢" if channel.is_active else "на паузе 🔴"
    mode = "с модерацией" if channel.moderation_mode else "автоматический"

    text = (
        f"<b>Управление каналом: {channel.channel_name}</b>\n\n"
        f"<b>Тема:</b> {channel.topic}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Режим AI:</b> {mode} (модель: <code>{channel.ai_model}</code>)\n"
        f"<b>Интервал постов:</b> ~{channel.post_interval // 60} мин."
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboards.channel_menu(channel_id)
    )


@router.callback_query(F.data.startswith("rss_"))
async def rss_sources_menu(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    sources = db.query(RSSSource).filter(RSSSource.channel_id == channel_id).all()
    db.close()

    text = "📰 У вас пока нет RSS-источников." if not sources else "📰 Ваши RSS-источники:"
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.rss_sources_menu(channel_id, sources)
    )


@router.callback_query(F.data.startswith("add_rss_"))
async def add_rss_manual_start(callback: CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split("_")[2])
    await state.update_data(channel_id=channel_id)
    await callback.message.edit_text(
        "📡 Введите URL RSS-ленты напрямую.\n\n"
        "Примеры популярных RSS:\n"
        "• <code>https://habr.com/ru/rss/all/all/</code> - Хабр\n"
        "• <code>https://vc.ru/rss</code> - VC.ru\n"
        "• <code>https://www.vedomosti.ru/rss/news</code> - Ведомости\n"
        "• <code>https://lenta.ru/rss</code> - Лента.ру"
    )
    await state.set_state(ChannelStates.waiting_manual_rss)


@router.message(StateFilter(ChannelStates.waiting_manual_rss))
async def process_manual_rss(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_id = data['channel_id']

    url_input = message.text.strip()
    if not url_input.startswith(('http://', 'https://')):
        formatted_url = f"https://{url_input}"
    else:
        formatted_url = url_input

    import feedparser
    feed = feedparser.parse(formatted_url)

    if feed.entries:
        db = SessionLocal()
        title = feed.feed.get('title', formatted_url[:50])
        add_rss_source(db, channel_id, formatted_url, title)
        sources = db.query(RSSSource).filter_by(channel_id=channel_id).all()
        db.close()

        await message.answer(
            f"✅ RSS источник '{title}' успешно добавлен!",
            reply_markup=keyboards.rss_sources_menu(channel_id, sources)
        )
    else:
        await message.answer(
            "❌ Не удалось прочитать RSS по указанному URL. Проверьте правильность ссылки."
        )

    await state.clear()


@router.callback_query(F.data.startswith("create_"))
async def create_post_start(callback: CallbackQuery, bot: Bot):
    channel_id = int(callback.data.split("_")[1])

    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    sources = db.query(RSSSource).filter_by(channel_id=channel_id, is_active=True).all()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        db.close()
        return

    if not sources:
        await callback.answer("Сначала добавьте RSS источники!", show_alert=True)
        db.close()
        return

    msg = await safe_edit_text(callback.message, "⏳ Ищу свежие новости...")

    try:
        from core.rss_parser import RSSParser
        ai_processor = AIProcessor()
        publisher = Publisher(bot)

        parser = RSSParser()
        async with parser:
            all_entries = []
            for source in sources:
                entries = await parser.parse_feed(source.url)
                if entries:
                    all_entries.extend(entries[:3])

            if not all_entries:
                await safe_edit_text(msg, "❌ Не найдено новых новостей в источниках.")
                db.close()
                return

            await safe_edit_text(msg, "🧠 Обрабатываю новость с помощью AI...")
            
            # Ищем новость, которая еще не была опубликована
            selected_entry = None
            for entry in all_entries:
                if not check_post_duplicate(db, channel_id, entry['title'], entry['content'], entry.get('guid')):
                    selected_entry = entry
                    break
            
            if not selected_entry:
                await safe_edit_text(msg, "❌ Все найденные новости уже были опубликованы.")
                db.close()
                return
            
            entry = selected_entry

            processed_content = await ai_processor.process_content(
                entry,
                {
                    'ai_model': channel.ai_model,
                    'ai_prompt': channel.ai_prompt,
                    'topic': channel.topic
                }
            )

            media_urls = entry.get('media', [])

            await safe_edit_text(msg, "✅ Готово! Публикую пост в канал...")
            # Вместо немедленной публикации — кладем пост В ОЧЕРЕДЬ строго по расписанию
            last_post = db.query(Post).filter_by(channel_id=channel_id).order_by(Post.scheduled_time.desc()).first()
            if last_post and last_post.scheduled_time and last_post.scheduled_time > datetime.utcnow():
                next_time = last_post.scheduled_time + timedelta(seconds=channel.post_interval)
            else:
                # Если нет постов или они в прошлом — ставим ближайшее время от текущего
                next_time = datetime.utcnow() + timedelta(minutes=5)

            new_post = create_post(
                db, channel_id, sources[0].url,
                entry['title'], entry['content'],
                processed_content, media_urls,
                next_time, entry.get('guid')
            )

            await safe_edit_text(
                msg,
                "✅ Пост добавлен в очередь и будет опубликован по расписанию",
                reply_markup=keyboards.channel_menu(channel_id)
            )

    except Exception as e:
        await safe_edit_text(msg, f"❌ Произошла ошибка: {str(e)[:100]}")
    finally:
        db.close()


@router.callback_query(F.data.startswith("queue_"))
async def show_queue(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    posts = get_channel_queue(db, channel_id)
    db.close()

    if not posts:
        await safe_edit_text(callback.message,
            "📭 Очередь постов пуста",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel_{channel_id}")]
            ])
        )
    else:
        await safe_edit_text(callback.message,
            f"📝 В очереди {len(posts)} постов",
            reply_markup=keyboards.post_queue_menu(channel_id, posts)
        )


@router.callback_query(F.data.startswith("post_"))
async def show_post_preview(callback: CallbackQuery, bot: Bot):
    post_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    post = db.query(Post).filter_by(id=post_id).first()
    db.close()
    
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return
    
    # Формируем предварительный просмотр поста
    status_emoji = {
        "pending": "⏳",
        "published": "✅",
        "moderation": "👁️",
        "rejected": "❌"
    }.get(post.status, "❓")
    
    preview_text = (
        f"<b>📝 Предварительный просмотр поста</b>\n\n"
        f"<b>Оригинальный заголовок:</b> {post.original_title[:80]}\n"
        f"<b>Время публикации:</b> {post.scheduled_time.strftime('%d.%m.%Y %H:%M')}\n"
        f"<b>Статус:</b> {status_emoji} {post.status}\n"
        f"<b>Источник:</b> {post.source_url[:50]}...\n\n"
        f"<b>📄 Финальный текст поста:</b>\n"
        f"{'─' * 30}\n"
        f"{post.processed_content}\n"
        f"{'─' * 30}"
    )
    
    # Создаем клавиатуру для действий с постом
    keyboard = []
    
    # Добавляем кнопки в зависимости от статуса поста
    if post.status == "pending":
        keyboard.append([
            InlineKeyboardButton(text="✅ Опубликовать сейчас", callback_data=f"publish_post_{post_id}"),
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_post_{post_id}")
        ])
    elif post.status == "moderation":
        keyboard.append([
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_post_{post_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_post_{post_id}")
        ])
    
    # Общие действия
    keyboard.append([
        InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_post_{post_id}"),
        InlineKeyboardButton(text="📋 Копировать текст", callback_data=f"copy_post_{post_id}")
    ])
    
    keyboard.append([
        InlineKeyboardButton(text="◀️ Назад к очереди", callback_data=f"queue_{post.channel_id}")
    ])
    
    await callback.message.edit_text(
        preview_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("publish_now_"))
async def publish_next_post(callback: CallbackQuery, bot: Bot):
    channel_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    
    # Находим первый пост в очереди
    post = db.query(Post).filter(
        Post.channel_id == channel_id,
        Post.status == "pending"
    ).order_by(Post.scheduled_time).first()
    
    if not post:
        await callback.answer("В очереди нет постов для публикации", show_alert=True)
        db.close()
        return
    
    # Публикуем пост
    try:
        from core.publisher import Publisher
        publisher = Publisher(bot)
        
        channel = db.query(Channel).filter_by(id=channel_id).first()
        message_id = await publisher.publish_post(
            channel.channel_id,
            post.processed_content,
            post.media_urls
        )
        
        if message_id:
            update_post_status(db, post.id, "published", message_id)
            await callback.answer(f"Пост опубликован в канале {channel.channel_name}!", show_alert=True)
        else:
            await callback.answer("Ошибка при публикации поста", show_alert=True)
            
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)[:100]}", show_alert=True)
    finally:
        db.close()
    
    # Возвращаемся к очереди
    callback.data = f"queue_{channel_id}"
    await show_queue(callback)


@router.callback_query(F.data.startswith("clear_queue_"))
async def clear_queue_confirm(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    posts_count = db.query(Post).filter(
        Post.channel_id == channel_id,
        Post.status == "pending"
    ).count()
    db.close()
    
    if posts_count == 0:
        await callback.answer("Очередь уже пуста", show_alert=True)
        return
    
    keyboard = [
        [
            InlineKeyboardButton(text="✅ Да, очистить", callback_data=f"confirm_clear_queue_{channel_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"queue_{channel_id}")
        ]
    ]
    
    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить все {posts_count} постов из очереди?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("confirm_clear_queue_"))
async def clear_queue_execute(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[3])
    db = SessionLocal()
    
    deleted_count = db.query(Post).filter(
        Post.channel_id == channel_id,
        Post.status == "pending"
    ).delete()
    
    db.commit()
    db.close()
    
    await callback.answer(f"Удалено {deleted_count} постов из очереди", show_alert=True)
    
    # Возвращаемся к очереди
    callback.data = f"queue_{channel_id}"
    await show_queue(callback)


@router.callback_query(F.data.startswith("publish_post_"))
async def publish_specific_post(callback: CallbackQuery, bot: Bot):
    post_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    post = db.query(Post).filter_by(id=post_id).first()
    
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        db.close()
        return
    
    try:
        from core.publisher import Publisher
        publisher = Publisher(bot)
        
        channel = db.query(Channel).filter_by(id=post.channel_id).first()
        message_id = await publisher.publish_post(
            channel.channel_id,
            post.processed_content,
            post.media_urls
        )
        
        if message_id:
            update_post_status(db, post.id, "published", message_id)
            await callback.answer(f"Пост опубликован в канале {channel.channel_name}!", show_alert=True)
            
            # Возвращаемся к очереди
            callback.data = f"queue_{post.channel_id}"
            await show_queue(callback)
        else:
            await callback.answer("Ошибка при публикации поста", show_alert=True)
            
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)[:100]}", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("delete_post_"))
async def delete_specific_post(callback: CallbackQuery):
    post_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    post = db.query(Post).filter_by(id=post_id).first()
    
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        db.close()
        return
    
    channel_id = post.channel_id
    post_title = post.original_title[:50]
    
    # Удаляем пост используя функцию из CRUD
    if delete_post(db, post_id):
        await callback.answer(f"Пост «{post_title}» удален", show_alert=True)
    else:
        await callback.answer("Ошибка при удалении поста", show_alert=True)
    
    db.close()
    
    # Возвращаемся к очереди
    callback.data = f"queue_{channel_id}"
    await show_queue(callback)


@router.callback_query(F.data.startswith("edit_post_"))
async def edit_post_start(callback: CallbackQuery, state: FSMContext):
    post_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    post = db.query(Post).filter_by(id=post_id).first()
    db.close()
    
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return
    
    await state.update_data(post_id=post_id, channel_id=post.channel_id)
    await callback.message.edit_text(
        f"<b>Редактирование поста</b>\n\n"
        f"<b>Текущий текст:</b>\n"
        f"{post.processed_content}\n\n"
        f"Отправьте новый текст поста:"
    )
    await state.set_state(ChannelStates.editing_post)


@router.message(StateFilter(ChannelStates.editing_post))
async def process_post_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    post_id = data['post_id']
    channel_id = data['channel_id']
    
    db = SessionLocal()
    
    # Используем функцию из CRUD для обновления контента
    post = update_post_content(db, post_id, message.text)
    
    if post:
        await message.answer("✅ Пост успешно отредактирован!")
    else:
        await message.answer("❌ Пост не найден")
    
    db.close()
    await state.clear()
    
    # Возвращаемся к очереди
    from aiogram.types.user import User
    from aiogram.types.chat import Chat
    
    callback_to_return = CallbackQuery(
        id="return_to_queue",
        from_user=message.from_user,
        chat_instance="dummy",
        message=message,
        data=f"queue_{channel_id}"
    )
    await show_queue(callback_to_return)


@router.callback_query(F.data.startswith("copy_post_"))
async def copy_post_text(callback: CallbackQuery):
    post_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    post = db.query(Post).filter_by(id=post_id).first()
    db.close()
    
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        return
    
    # Отправляем текст поста как обычное сообщение для копирования
    await callback.message.answer(
        f"<b>📋 Текст поста для копирования:</b>\n\n"
        f"<code>{post.processed_content}</code>",
        parse_mode="HTML"
    )
    await callback.answer("Текст скопирован в чат", show_alert=True)


@router.callback_query(F.data.startswith("approve_post_"))
async def approve_post(callback: CallbackQuery, bot: Bot):
    post_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    post = db.query(Post).filter_by(id=post_id).first()
    
    if not post:
        await callback.answer("Пост не найден", show_alert=True)
        db.close()
        return
    
    try:
        from core.publisher import Publisher
        publisher = Publisher(bot)
        
        channel = db.query(Channel).filter_by(id=post.channel_id).first()
        message_id = await publisher.publish_post(
            channel.channel_id,
            post.processed_content,
            post.media_urls
        )
        
        if message_id:
            update_post_status(db, post.id, "published", message_id)
            await callback.answer(f"Пост одобрен и опубликован в канале {channel.channel_name}!", show_alert=True)
            
            # Возвращаемся к очереди
            callback.data = f"queue_{post.channel_id}"
            await show_queue(callback)
        else:
            await callback.answer("Ошибка при публикации поста", show_alert=True)
            
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)[:100]}", show_alert=True)
    finally:
        db.close()


@router.callback_query(F.data.startswith("reject_post_"))
async def reject_post(callback: CallbackQuery):
    post_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    
    if update_post_status(db, post_id, "rejected"):
        await callback.answer("Пост отклонен", show_alert=True)
        
        # Возвращаемся к очереди
        post = db.query(Post).filter_by(id=post_id).first()
        if post:
            callback.data = f"queue_{post.channel_id}"
            await show_queue(callback)
    else:
        await callback.answer("Ошибка при отклонении поста", show_alert=True)
    
    db.close()


@router.callback_query(F.data.startswith("toggle_"))
async def toggle_channel_active(callback: CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = crud.toggle_channel_active(db, channel_id)
    db.close()

    if channel:
        status = "запущен" if channel.is_active else "поставлен на паузу"
        await callback.answer(f"Канал {status}")
        await channel_menu(callback, state)


@router.callback_query(F.data.startswith("schedule_"))
async def schedule_menu(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()
    if not channel:
        await callback.answer("Канал не найден", show_alert=True)
        return

    text = f"⏰ Текущий интервал между постами: ~{channel.post_interval // 60} минут.\n\nВыберите новый интервал:"
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.schedule_menu(channel_id, channel.post_interval)
    )


@router.callback_query(F.data.startswith("set_interval_"))
async def set_schedule(callback: CallbackQuery):
    try:
        _, _, channel_id_str, interval_str = callback.data.split("_")
        channel_id = int(channel_id_str)
        interval = int(interval_str)
    except ValueError:
        await callback.answer("Ошибка данных. Попробуйте снова.", show_alert=True)
        return

    db = SessionLocal()
    update_channel_settings(db, channel_id, post_interval=interval)
    db.close()

    await callback.answer(f"Интервал изменен на ~{interval // 60} минут.", show_alert=True)

    callback.data = f"schedule_{channel_id}"
    await schedule_menu(callback)


@router.callback_query(F.data.startswith("delete_rss_"))
async def delete_rss_confirm(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    source = db.query(RSSSource).filter_by(id=source_id).first()
    if not source:
        await callback.answer("RSS источник не найден", show_alert=True)
        db.close()
        return
    
    channel_id = source.channel_id
    db.close()
    
    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить RSS источник «{source.name}»?",
        reply_markup=keyboards.confirm_delete_rss(source_id, channel_id)
    )


@router.callback_query(F.data.startswith("delete_"))
async def delete_channel_confirm(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()
    if not channel:
        await callback.answer("Канал не найден", show_alert=True)
        return

    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить канал «{channel.channel_name}» и все связанные с ним данные?",
        reply_markup=keyboards.confirm_delete(channel_id)
    )


@router.callback_query(F.data.startswith("confirm_delete_rss_"))
async def delete_rss_execute(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[3])
    db = SessionLocal()
    source = db.query(RSSSource).filter_by(id=source_id).first()
    if source:
        channel_id = source.channel_id
        source_name = source.name
        delete_rss_source(db, source_id)
        sources = db.query(RSSSource).filter_by(channel_id=channel_id).all()
        
        await callback.answer(f"RSS источник «{source_name}» удален", show_alert=True)
        await callback.message.edit_text(
            "📰 Ваши RSS-источники:" if sources else "📰 У вас пока нет RSS-источников.",
            reply_markup=keyboards.rss_sources_menu(channel_id, sources)
        )
    else:
        await callback.answer("RSS источник не найден", show_alert=True)
    db.close()


@router.callback_query(F.data.startswith("confirm_delete_"))
async def delete_channel_execute(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    delete_channel(db, channel_id)
    db.close()

    await callback.answer("Канал успешно удален", show_alert=True)
    await show_channels(callback)


@router.callback_query(F.data.regexp(r"^ai_\d+$"))
async def ai_settings_menu(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        return

    text = (
        f"<b>Настройки AI для канала «{channel.channel_name}»</b>\n\n"
        f"<b>Текущая модель:</b> <code>{channel.ai_model}</code>\n"
        f"<b>Режим модерации:</b> {'Включен' if channel.moderation_mode else 'Выключен'}\n\n"
        "Здесь вы можете изменить модель, которая будет обрабатывать тексты, или отредактировать системный промпт."
    )
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.ai_settings_menu(channel_id, channel.moderation_mode)
    )


@router.callback_query(F.data.startswith("ai_model_"))
async def choose_ai_model(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        return

    await callback.message.edit_text(
        "Выберите модель, которую бот будет использовать для обработки новостей:",
        reply_markup=keyboards.ai_models_menu(channel_id, channel.ai_model)
    )


@router.callback_query(F.data.startswith("ai_prompt_"))
async def ai_prompt_change_start(callback: CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        return

    current_prompt = channel.ai_prompt or "Пока не задан. Будет использован стандартный."

    await state.update_data(channel_id=channel_id)
    await callback.message.edit_text(
        f"<b>Текущий промпт:</b>\n<pre>{current_prompt}</pre>\n\n"
        "Отправьте новый текст системного промпта. Используйте `{topic}` для подстановки темы канала."
    )
    await state.set_state(ChannelStates.waiting_ai_prompt)


@router.message(StateFilter(ChannelStates.waiting_ai_prompt))
async def process_ai_prompt(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_id = data['channel_id']

    db = SessionLocal()
    update_channel_settings(db, channel_id, ai_prompt=message.text)
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()

    await message.answer("✅ Системный промпт успешно обновлен!")
    await state.clear()

    from aiogram.types.user import User
    from aiogram.types.chat import Chat

    callback_to_return = CallbackQuery(
        id="return_to_ai_menu",
        from_user=message.from_user,
        chat_instance="dummy",
        message=message,
        data=f"ai_{channel_id}"
    )
    await ai_settings_menu(callback_to_return)


@router.callback_query(F.data.startswith("set_model_"))
async def set_ai_model(callback: CallbackQuery):
    parts = callback.data.split("_")
    channel_id = int(parts[2])
    model = "-".join(parts[3:])

    db = SessionLocal()
    update_channel_settings(db, channel_id, ai_model=model)
    db.close()

    await callback.answer(f"Модель изменена на {model}", show_alert=True)
    await ai_settings_menu(callback)


@router.callback_query(F.data.startswith("moderation_"))
async def toggle_moderation(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    if channel:
        new_mode = not channel.moderation_mode
        update_channel_settings(db, channel_id, moderation_mode=new_mode)
        mode_text = "включен" if new_mode else "выключен"
        await callback.answer(f"Режим модерации {mode_text}")
        await ai_settings_menu(callback)
    db.close()
