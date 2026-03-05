import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jobmate.db")
CHECKIN_HOUR: int = int(os.getenv("CHECKIN_HOUR", "8"))   # 8 AM local (UTC for now)
MATCH_THRESHOLD: int = int(os.getenv("MATCH_THRESHOLD", "50"))
DAILY_APPLY_LIMIT: int = int(os.getenv("DAILY_APPLY_LIMIT", "10"))
