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
        try:
            rsp = await g4f.ChatCompletion.create_async(model=self._SAFE_MODEL, messages=[
                {"role": "user", "content": "Translate to Russian:\n\n{}".format(text)}])
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
            tokens = stripped.split()
            if tokens and sum(1 for w in tokens if w.startswith('#')) >= max(1, int(len(tokens) * 0.6)):
                continue
            # Удаляем хештеги внутри предложений: `#word` -> `word`
            no_tags = re.sub(r'(^|\s)#(\w+)', r'\1\2', line)
            cleaned_lines.append(no_tags)

        txt = "\n".join(cleaned_lines)

        if not re.search(r"[📰🔥💡🚀⚡✨🎯💻🤖]", txt):
            txt = "{} {}".format(random.choice(self._emojis_for(topic)), txt)

        return txt[:1000]

    async def _ensure_russian(self, text: str) -> str:
        """Если модель вернула не-русский текст, дозакажем перевод."""
        try:
            # Доля кириллических символов в тексте
            letters = [c for c in text if c.isalpha()]
            if not letters:
                return text
            cyr = sum(1 for c in letters if 'а' <= c.lower() <= 'я' or c.lower() == 'ё')
            ratio = cyr / max(1, len(letters))
            if ratio < 0.3:
                return await self.simple_translate(text)
            return text
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
        return "Ты — профессиональный редактор русскоязычного телеграм-канала на тему \"{topic}\". Задача: переведи и адаптируй новость НА РУССКИЙ ЯЗЫК.\n\nПравила:\n1. Пиши по-русски, сохраняй смысл.\n2. Не переводить названия компаний/продуктов (Apple и т.п.).\n3. Формат: жирный заголовок без кавычек + 2–3 абзаца, ≤900 символов. Один из абзацев (самый важный) оформи как цитату, используя теги <i> и </i>.\n4. Стиль: без воды.\n5. НЕ используй хештеги вообще. Не добавляй их ни в конце, ни в тексте."
