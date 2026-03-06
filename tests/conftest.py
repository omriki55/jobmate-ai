"""
Shared test fixtures for JobMate AI.
Uses an in-memory SQLite database so tests are fast and isolated.
"""
import asyncio
import os
import sys

import pytest
import pytest_asyncio

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force test settings BEFORE importing anything else
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"  # in-memory
os.environ["ENVIRONMENT"] = "dev"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ANTHROPIC_API_KEY"] = ""  # force fallback mode

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database — create fresh in-memory DB per test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Modules that import AsyncSessionLocal and need patching
# ---------------------------------------------------------------------------

_MODULES_WITH_SESSION = [
    "db.database",
    "web.app",
    "web.auth",
    "services.job_scraper",
    "services.job_search",
]


@pytest_asyncio.fixture
async def patched_app(db_engine):
    """Patch AsyncSessionLocal in all modules that import it."""
    import importlib

    test_session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    originals = {}
    for mod_name in _MODULES_WITH_SESSION:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "AsyncSessionLocal"):
                originals[mod_name] = mod.AsyncSessionLocal
                mod.AsyncSessionLocal = test_session_factory
        except ImportError:
            pass

    # Also patch engine in db.database for health check
    import db.database as db_mod
    orig_engine = db_mod.engine
    db_mod.engine = db_engine

    from web.app import app
    yield app

    # Restore
    db_mod.engine = orig_engine
    for mod_name, orig in originals.items():
        mod = importlib.import_module(mod_name)
        mod.AsyncSessionLocal = orig


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(patched_app):
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_token(client):
    """Create a test user and return a valid JWT token."""
    resp = await client.post("/api/session/init", json={"session_id": "test-session-123"})
    assert resp.status_code == 200
    return resp.json()["token"]


def auth_headers(token: str) -> dict:
    """Return Authorization header dict for authenticated requests."""
    return {"Authorization": f"Bearer {token}"}
