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
        return sanitize_html(self._finalize_post(raw, topic))

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
        hashtags = " ".join(self._hashtags_for(topic))
        clean_title = title_ru.strip(' "\'')
        return "<b>{} {}</b>\n\n{}\n\n{}".format(emoji, clean_title, body, hashtags)[:1000]

    def _finalize_post(self, raw: str, topic: str) -> str:
        txt = raw.strip()
        if any(sym in txt for sym in ("**", "__", "`")):
            txt = md_to_html(txt)

        lines = txt.split("\n")

        if lines and "<b>" not in lines[0]:
            first = lines[0].strip(' "\'')
            lines[0] = "<b>{}</b>".format(first)

        # Убираем все строки с хештегами из основного текста
        cleaned_lines = []
        hashtag_line = None
        
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and '#' in line_stripped:
                # Проверяем, является ли строка строкой хештегов
                words = line_stripped.split()
                hashtag_count = sum(1 for word in words if word.startswith('#'))
                if hashtag_count >= len(words) * 0.5:  # Если больше половины слов - хештеги
                    hashtag_line = line_stripped
                else:
                    cleaned_lines.append(line)  # Обычная строка с хештегами внутри
            else:
                cleaned_lines.append(line)

        # Обрабатываем найденную строку хештегов
        final_hashtags = self._hashtags_for(topic)
        if hashtag_line:
            existing_tags = [tag.lstrip('#') for tag in hashtag_line.split() if tag.startswith('#')]
            # Берем только первые 3 хештега из существующих или добавляем стандартные
            if len(existing_tags) <= 3:
                final_hashtags = [f"#{tag}" for tag in existing_tags[:3]]
            else:
                final_hashtags = [f"#{tag}" for tag in existing_tags[:3]]

        txt = "\n".join(cleaned_lines)

        if not re.search(r"[📰🔥💡🚀⚡✨🎯💻🤖]", txt):
            txt = "{} {}".format(random.choice(self._emojis_for(topic)), txt)

        # Добавляем хештеги в конце, если их нет
        if not any('#' in line for line in txt.split('\n')):
            txt += "\n\n" + " ".join(final_hashtags)
        else:
            # Заменяем существующие хештеги на наши
            txt += "\n\n" + " ".join(final_hashtags)

        return txt[:1000]

    def _emojis_for(self, topic: str) -> List[str]:
        t = topic.lower()
        if any(w in t for w in ("it", "tech", "технолог", "программ", "код")):
            return self.emojis["tech"]
        if any(w in t for w in ("бизнес", "финанс", "экономик", "маркет")):
            return self.emojis["business"]
        return self.emojis["news"]

    def _hashtags_for(self, topic: str) -> List[str]:
        base = {
            "it": ["#tech", "#IT", "#технологии", "#инновации", "#разработка"],
            "криптовалют": ["#crypto", "#blockchain", "#криптовалюта", "#bitcoin", "#defi"],
            "маркетинг": ["#marketing", "#digital", "#реклама", "#smm", "#продвижение"],
            "бизнес": ["#business", "#стартап", "#предпринимательство", "#инвестиции", "#экономика"],
            "новости": ["#news", "#новости", "#сегодня", "#актуально", "#обновления"],
        }
        t = topic.lower()
        for k, tags in base.items():
            if k in t:
                return random.sample(tags, 3)
        
        # Если тема не найдена, генерируем 3 хештега
        topic_hashtag = topic.replace(" ", "_")[:15]
        return ["#news", "#{}".format(topic_hashtag), "#актуально"]

    @staticmethod
    def _default_prompt() -> str:
        return "Ты — профессиональный редактор русскоязычного телеграм-канала на тему \"{topic}\". Твоя задача — перевести и адаптировать новость.\n\nПравила:\n1. Переводи на русский, сохраняя смысл.\n2. Не переводим названия компаний/продуктов (Apple и т.д.).\n3. Формат: жирный заголовок без кавычек + 2–3 абзаца, ≤900 символов. Один из абзацев (самый важный) оформи как цитату, используя теги <i> и </i>.\n4. Стиль: без воды.\n5. В конце добавь РОВНО 3 релевантных хештега. Каждый хештег — одно слово и должен начинаться с символа #. НЕ добавляй хештеги в основной текст, только в самом конце отдельной строкой."
