from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from typing import Dict, Callable
import asyncio
from database.crud import *
from database.models import SessionLocal, Post
from core.rss_parser import RSSParser
from core.ai_processor import AIProcessor
from core.publisher import Publisher


class Scheduler:
    def __init__(self, bot):
        self.scheduler = AsyncIOScheduler()
        self.bot = bot
        self.publisher = Publisher(bot)
        self.ai_processor = AIProcessor()

    def start(self):
        self.scheduler.add_job(
            self.check_rss_sources,
            IntervalTrigger(seconds=1800),
            id='rss_checker',
            replace_existing=True
        )

        # Публикуем чаще, чтобы не копился лаг публикации, но всегда строго по очереди/времени
        self.scheduler.add_job(
            self.publish_scheduled_posts,
            IntervalTrigger(seconds=20),
            id='post_publisher',
            replace_existing=True
        )

        self.scheduler.start()

    async def check_rss_sources(self):
        db = SessionLocal()
        try:
            sources = get_active_sources(db)

            parser = RSSParser()
            async with parser:
                for source in sources:
                    try:
                        entries = await parser.parse_feed(source.url, source.last_guid)

                        if entries:
                            channel = source.channel

                            # Обрабатываем от старых к новым, чтобы очередь шла в правильном порядке
                            for entry in reversed(entries):
                                if not entry.get('media'):
                                    continue

                                # Проверяем дубликаты перед обработкой
                                if check_post_duplicate(db, channel.id, entry['title'], entry['content'], entry.get('guid')):
                                    continue

                                processed = await self.ai_processor.process_content(
                                    entry,
                                    {
                                        'ai_model': channel.ai_model,
                                        'ai_prompt': channel.ai_prompt,
                                        'topic': channel.topic
                                    }
                                )

                                last_post = db.query(Post).filter(
                                    Post.channel_id == channel.id
                                ).order_by(Post.scheduled_time.desc()).first()

                                # Всегда добавляем в очередь и рассчитываем корректное будущее время
                                if last_post and last_post.scheduled_time and last_post.scheduled_time > datetime.utcnow():
                                    next_time = last_post.scheduled_time + timedelta(seconds=channel.post_interval)
                                else:
                                    next_time = datetime.utcnow() + timedelta(minutes=5)

                                create_post(
                                    db, channel.id, source.url,
                                    entry['title'], entry['content'],
                                    processed, entry.get('media', []),
                                    next_time, entry.get('guid')
                                )

                            if entries:
                                # Сохраняем самый новый GUID как last_guid
                                update_source_check(db, source.id, entries[0]['guid'])

                    except Exception:
                        update_source_check(db, source.id, error=True)
        finally:
            db.close()

    async def publish_scheduled_posts(self):
        db = SessionLocal()
        try:
            # Берем только самый ранний готовый пост, чтобы соблюдать порядок
            posts = get_pending_posts(db)
            if not posts:
                return

            post = posts[0]
            channel = post.channel

            if not channel.is_active:
                return

            if channel.moderation_mode:
                update_post_status(db, post.id, "moderation")
                return

            # Публикуем строго тот пост, который первый по времени
            message_id = await self.publisher.publish_post(
                channel.channel_id,
                post.processed_content,
                post.media_urls
            )

            if message_id:
                update_post_status(db, post.id, "published", message_id)
            else:
                update_post_status(db, post.id, "failed")
        finally:
            db.close()

    def stop(self):
        self.scheduler.shutdown()
