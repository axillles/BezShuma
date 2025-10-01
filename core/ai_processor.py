import asyncio
import random
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

import g4f
from g4f.errors import ModelNotFoundError
from utils.helpers import sanitize_html


def is_http_url(s: str) -> bool:
    try:
        return urlparse(s).scheme in {"http", "https"}
    except Exception:
        return False


def md_to_html(text: str) -> str:
    try:
        import markdown2
    except ImportError:
        return text
    html = markdown2.markdown(text)
    html = html.replace("<strong>", "<b>").replace("</strong>", "</b>").replace("<em>", "<i>").replace("</em>", "</i>")
    html = re.sub(r"</?p>", "", html)
    return html


class AIProcessor:
    _SAFE_MODEL = "gpt-4o-mini"
    _SUPPORTED = {"gpt-4o-mini", "gpt-4"}

    def __init__(self) -> None:
        self.emojis = {
            "tech": ["💻", "🚀", "🔧", "⚡", "🌐", "📱", "🤖"],
            "news": ["📰", "📢", "🔥", "⚠️", "💡", "✨", "🎯"],
            "business": ["💼", "📈", "💰", "🏢", "📊", "🤝", "💸"],
        }

    async def process_content(self, entry: Dict, ch_settings: Dict) -> str:
        model = ch_settings.get("ai_model") or self._SAFE_MODEL
        if model not in self._SUPPORTED:
            model = self._SAFE_MODEL
        topic = ch_settings.get("topic", "новости")
        sys_prompt = (ch_settings.get("ai_prompt") or self._default_prompt().format(topic=topic))
        user_prompt = "Переработай эту новость в пост для Телеграм (до 900 симв.): Title: {}. Content: {}".format(
            entry['title'], entry['content'][:500])
        try:
            raw = await self._call_llm(model, sys_prompt, user_prompt)
        except ModelNotFoundError:
            raw = await self._call_llm(self._SAFE_MODEL, sys_prompt, user_prompt)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("AI error, fallback: %s", e)
            return await self._fallback_format(entry, topic)
        finalized = self._finalize_post(raw, topic)
        finalized = await self._ensure_russian(finalized)
        return sanitize_html(finalized)

    async def simple_translate(self, text: str) -> str:
        """Переводит произвольный текст на русский. Возвращает исходный текст при ошибке."""
        try:
            prompt = (
                "Переведи текст на литературный русский. Сохрани смысл, имена собственные и форматирование HTML. "
                "Отвечай ТОЛЬКО переведенным русским текстом без добавлений, без хештегов.\n\n{}"
            ).format(text)
            rsp = await g4f.ChatCompletion.create_async(
                model=self._SAFE_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
            return rsp
        except Exception:
            return text

    async def _call_llm(self, model: str, sys: str, user: str) -> str:
        return await asyncio.wait_for(g4f.ChatCompletion.create_async(model=model,
                                                                      messages=[{"role": "system", "content": sys},
                                                                                {"role": "user", "content": user}]),
                                      timeout=20)

    async def _fallback_format(self, entry: Dict, topic: str) -> str:
        title_ru = await self.simple_translate(entry['title'])
        cont_ru = await self.simple_translate(entry['content'])
        cont_ru = cont_ru.replace("\n\n", "\n")[:600]
        emoji = random.choice(self._emojis_for(topic))
        body = ". ".join(cont_ru.split(". ")[:4])
        if body and not body.endswith("."):
            body += "."
        clean_title = title_ru.strip(' "\'')
        return "<b>{} {}</b>\n\n{}".format(emoji, clean_title, body)[:1000]

    def _finalize_post(self, raw: str, topic: str) -> str:
        txt = raw.strip()
        if any(sym in txt for sym in ("**", "__", "`")):
            txt = md_to_html(txt)

        lines = txt.split("\n")

        if lines and "<b>" not in lines[0]:
            first = lines[0].strip(' "\'')
            lines[0] = "<b>{}</b>".format(first)

        # Полностью удаляем хештеги из текста: строки с множеством хештегов убираем,
        # одиночные хештеги внутри предложений удаляем
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue
            # Игнорируем строки, которые начинаются с # (заголовки/хэштеги)
            if stripped.startswith('#'):
                continue
            tokens = stripped.split()
            if tokens and sum(1 for w in tokens if w.startswith('#')) >= max(1, int(len(tokens) * 0.6)):
                continue
            # Удаляем хештеги внутри предложений: `#word` -> `word`
            no_tags = re.sub(r'(^|\s)#(\w+)', r'\1\2', line)
            # На всякий случай убираем остаточные токены-хэштеги вида #anything
            no_tags = re.sub(r'#\S+', '', no_tags)
            # Убираем двойные пробелы, возникшие после вырезания
            no_tags = re.sub(r'\s{2,}', ' ', no_tags).strip()
            cleaned_lines.append(no_tags)

        txt = "\n".join([l for l in cleaned_lines if l])

        if not re.search(r"[📰🔥💡🚀⚡✨🎯💻🤖]", txt):
            txt = "{} {}".format(random.choice(self._emojis_for(topic)), txt)

        return txt[:1000]

    async def _ensure_russian(self, text: str) -> str:
        """Гарантирует, что итоговый текст на русском. При необходимости выполняет повторный перевод."""
        try:
            def cyr_ratio(s: str) -> float:
                letters = [c for c in s if c.isalpha()]
                if not letters:
                    return 0.0
                cyr = sum(1 for c in letters if 'а' <= c.lower() <= 'я' or c.lower() == 'ё')
                return cyr / max(1, len(letters))

            ratio = cyr_ratio(text)
            if ratio >= 0.7:
                return text

            # Первая попытка перевода
            translated = await self.simple_translate(text)
            if cyr_ratio(translated) >= 0.7:
                return translated

            # Вторая (последняя) попытка перевода, если все еще не хватает кириллицы
            translated2 = await self.simple_translate(translated)
            if cyr_ratio(translated2) >= 0.7:
                return translated2

            return translated2
        except Exception:
            return text

    def _emojis_for(self, topic: str) -> List[str]:
        t = topic.lower()
        if any(w in t for w in ("it", "tech", "технолог", "программ", "код")):
            return self.emojis["tech"]
        if any(w in t for w in ("бизнес", "финанс", "экономик", "маркет")):
            return self.emojis["business"]
        return self.emojis["news"]

    def _hashtags_for(self, topic: str) -> List[str]:
        # Поддерживаем метод для обратной совместимости, но больше не используем хештеги
        return []

    @staticmethod
    def _default_prompt() -> str:
        return (
            "Ты — профессиональный редактор русскоязычного телеграм-канала на тему \"{topic}\". "
            "Задача: переведи и адаптируй новость НА РУССКИЙ ЯЗЫК. Всегда отвечай ТОЛЬКО по-русски.\n\n"
            "Правила:\n"
            "1. Пиши по-русски, сохраняй смысл.\n"
            "2. Не переводить названия компаний/продуктов (Apple и т.п.).\n"
            "3. Формат: жирный заголовок без кавычек + 2–3 абзаца, ≤900 символов. "
            "Один из абзацев (самый важный) оформи как цитату, используя теги <i> и </i>.\n"
            "4. Стиль: без воды.\n"
            "5. НЕ используй хештеги вообще. Не добавляй их ни в конце, ни в тексте."
        )
