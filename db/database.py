from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from db.models import Base
from config.settings import DATABASE_URL, ENVIRONMENT

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
# Init — create tables in dev, skip in prod (Alembic handles it)
# ---------------------------------------------------------------------------

async def init_db() -> None:
    if ENVIRONMENT != "production":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
