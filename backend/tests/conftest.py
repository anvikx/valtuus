import os
from collections.abc import Iterator

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.adapters.memory.repositories import InMemoryAgentKeyRepository
from app.adapters.postgres.database import Database

# Tests never read the real key or database from .env. app.main builds the app at import
# time, so the values must be set before any test module imports it.
os.environ["AGENT_KEY"] = "test-agent-key-0123456789"
os.environ["DATABASE_URL"] = ""

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
# TRUNCATE, not DELETE: the audit trigger refuses DELETE, and TRUNCATE fires no row trigger.
_TRUNCATE = text(
    "TRUNCATE mandates, agent_keys, users, offers, carts, orders, audit_records,"
    " idempotency_keys RESTART IDENTITY",
)


@pytest.fixture
def agent_keys() -> InMemoryAgentKeyRepository:
    """Pass it to create_app; the demo key is seeded here, so a test can change it."""
    return InMemoryAgentKeyRepository()


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[Database]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set; CI sets it and runs the Postgres tests")

    database = Database.from_url(SecretStr(TEST_DATABASE_URL))
    database.migrate()
    yield database
    database.close()


@pytest.fixture
def database(migrated_database: Database) -> Database:
    """An empty, migrated database for each test."""
    with migrated_database.transaction():
        migrated_database.writer().execute(_TRUNCATE)

    return migrated_database
