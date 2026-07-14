from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

def _parse_admin_ids(value: str) -> set[int]:
    return {int(item.strip()) for item in value.split(",") if item.strip()}

@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    channel_username: str
    admin_ids: set[int]
    support_contact: str
    group_chat_id: int | None

def _normalize_database_url(url: str) -> str:
    """Convert Railway PostgreSQL URLs to SQLAlchemy asyncpg URLs."""
    value = url.strip()
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value

def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN در فایل .env تنظیم نشده است.")

    group_raw = os.getenv("GROUP_CHAT_ID", "").strip()
    return Settings(
        bot_token=token,
        database_url=_normalize_database_url(
            os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./kazhwan.db")
        ),
        channel_username=os.getenv(
            "CHANNEL_USERNAME", "@Kazhwantravel"
        ).strip(),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "86054420")),
        support_contact=os.getenv(
            "SUPPORT_CONTACT", "@Kazhwantravel"
        ).strip(),
        group_chat_id=int(group_raw) if group_raw else None,
    )
