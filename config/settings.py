import os
import secrets

from dotenv import load_dotenv

load_dotenv()

# ── Required ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# ── Database ──────────────────────────────────────────────
_raw_db_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./jobmate.db")
# Render/Heroku give postgres:// — SQLAlchemy needs postgresql+asyncpg://
if _raw_db_url.startswith("postgres://"):
    _raw_db_url = _raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw_db_url.startswith("postgresql://"):
    _raw_db_url = _raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
DATABASE_URL: str = _raw_db_url

# ── Security ─────────────────────────────────────────────
SECRET_KEY: str = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "dev")          # dev | production
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "*").split(",")
    if o.strip()
]

# ── Upload limits ────────────────────────────────────────
MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "10"))

# ── Logging ──────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── App defaults ─────────────────────────────────────────
CHECKIN_HOUR: int = int(os.getenv("CHECKIN_HOUR", "8"))      # Daily check-in hour (UTC, 0-23)
MATCH_THRESHOLD: int = int(os.getenv("MATCH_THRESHOLD", "50"))
DAILY_APPLY_LIMIT: int = int(os.getenv("DAILY_APPLY_LIMIT", "10"))
