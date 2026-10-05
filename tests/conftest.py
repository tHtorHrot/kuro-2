import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from jarvis.core.config import Settings
from jarvis.main import create_app
from jarvis.storage.database import Database


@pytest.fixture
def settings():
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://jarvis_app:test-password@localhost:5432/jarvis_test",
        token_pepper=SecretStr("test-only-pepper-" + "p" * 43),
    )


class OfflineDatabase:
    """Unit-test boundary only; PostgreSQL integration uses the real Database class."""

    def __init__(self, settings):
        self.settings = settings
        self.closed = False
        self.healthy = True

    async def verify_runtime_role(self):
        return None

    async def ready(self):
        return self.healthy

    async def close(self):
        self.closed = True


@pytest.fixture
def app(settings):
    return create_app(settings, OfflineDatabase(settings))


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def test_db(settings):
    url = os.getenv("JARVIS_TEST_DATABASE_URL")
    if not url:
        if os.getenv("JARVIS_REQUIRE_INTEGRATION") == "1":
            pytest.fail("JARVIS_TEST_DATABASE_URL is required in this test run")
        pytest.skip("Native PostgreSQL *_test database not configured")
    parsed = make_url(url)
    if not (parsed.database or "").endswith("_test") or parsed.username != "jarvis_app":
        pytest.fail("Integration requires jarvis_app on an isolated *_test database")
    db = Database(settings.model_copy(update={"database_url": SecretStr(url)}))
    assert await db.ready(), "Apply the migration to the isolated test database first"
    try:
        yield db
    finally:
        await db.close()
