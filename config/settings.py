import os
from dotenv import load_dotenv

load_dotenv()


def _normalize_database_url(raw_url: str | None) -> str:
    """Normalize DATABASE_URL from environment to a SQLAlchemy-compatible URL.

    - If empty or None: fallback to SQLite file.
    - If starts with https:// (e.g., Supabase REST URL by mistake): fallback to SQLite and warn via env var.
    - If starts with postgres://: convert to postgresql+psycopg2:// (SQLAlchemy recommended driver alias).
    - If starts with postgresql:// (without driver): leave as is (SQLAlchemy will choose available driver).
    """
    default_sqlite = "sqlite:///bot.db"
    if not raw_url:
        return default_sqlite

    url = raw_url.strip()
    # Misconfigured REST/base URL accidentally put into DATABASE_URL
    if url.lower().startswith("https://"):
        # Soft fallback to SQLite; users can fix .env later
        return default_sqlite

    # Old Heroku-style scheme
    if url.lower().startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]

    # Accept common correct forms as-is
    return url


BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL"))
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
RSS_CHECK_INTERVAL = 3600
MAX_CHANNELS_PER_USER = 5
MAX_RSS_PER_CHANNEL = 10
DEFAULT_POST_INTERVAL = 7200
MAX_QUEUE_SIZE = 50
AI_MODELS = ["gpt-4o-mini", "gpt-4"]
DEFAULT_AI_MODEL = "gpt-4o-mini"
