import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from db.models import Base
from config.settings import DATABASE_URL, ENVIRONMENT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine — with connection pool tuning for PostgreSQL
# ---------------------------------------------------------------------------

_is_sqlite = DATABASE_URL.startswith("sqlite")

_engine_kwargs: dict = {"echo": False}

if not _is_sqlite:
    # PostgreSQL pool settings (ignored by SQLite)
    _engine_kwargs.update(
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,      # detect stale connections
        pool_recycle=300,         # recycle connections every 5 min
    )

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Auto-migration — add missing columns to existing tables
# ---------------------------------------------------------------------------

def _add_missing_columns(conn) -> None:
    """Compare ORM models to DB and ALTER TABLE to add any missing columns."""
    inspector = inspect(conn)
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        for col in table.columns:
            if col.name not in existing:
                col_type = col.type.compile(conn.dialect)
                stmt = f'ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}'
                conn.execute(text(stmt))
                logger.info("Added column %s.%s (%s)", table_name, col.name, col_type)


# ---------------------------------------------------------------------------
# Init — create tables + migrate missing columns
# ---------------------------------------------------------------------------

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
