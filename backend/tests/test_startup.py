import dataclasses

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.adapters.catalog_downloader import CatalogDownloader
from app.adapters.postgres.database import Database
from app.adapters.postgres.repositories import PostgresAgentKeyRepository
from app.adapters.product_store import ProductStore
from app.config import Settings
from app.domain.agent_key import hash_agent_key
from app.domain.enums import AgentKeyStatus
from app.main import create_app
from tests.conftest import TEST_DATABASE_URL

_KEY = "test-agent-key-0123456789"


def _start_and_stop(settings: Settings) -> None:
    """The lifespan runs on enter and exit, so the engine closes as on a real stop."""
    with TestClient(create_app(settings)):
        pass


def test_app_refuses_to_start_without_agent_key() -> None:
    """With no key the agent door would have no working credential, so the deploy must fail."""
    settings = Settings(agent_key=SecretStr(""))

    with pytest.raises(ValueError, match="empty"):
        create_app(settings)


def test_catalog_is_loaded_before_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(CatalogDownloader, "download", lambda self: events.append("download"))
    monkeypatch.setattr(ProductStore, "load", lambda self, files: events.append("load"))

    with TestClient(create_app()) as client:
        assert events == ["download", "load"]
        assert client.get("/api/health").status_code == 200


def test_catalog_error_prevents_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: ProductStore, files: object) -> None:
        raise ValueError("invalid catalog")

    monkeypatch.setattr(ProductStore, "load", fail)
    with pytest.raises(ValueError, match="invalid catalog"), TestClient(create_app()):
        pass


def test_restart_keeps_a_revoked_key_revoked(database: Database) -> None:
    """A revoke must survive a deploy; else the restart gives a leaked key its access back."""
    settings = Settings(
        agent_key=SecretStr(_KEY),
        database_url=SecretStr(TEST_DATABASE_URL),
    )
    _start_and_stop(settings)
    agent_keys = PostgresAgentKeyRepository(database)
    agent = agent_keys.by_hash(hash_agent_key(_KEY))
    assert agent is not None
    with database.transaction():
        agent_keys.add(dataclasses.replace(agent, status=AgentKeyStatus.REVOKED))

    _start_and_stop(settings)

    restarted = agent_keys.by_hash(hash_agent_key(_KEY))
    assert restarted is not None
    assert restarted.status is AgentKeyStatus.REVOKED


@pytest.mark.parametrize("should_skip", [False, True])
def test_rollback_can_skip_newer_revisions(database, monkeypatch, should_skip):
    """A rollback image must start without asking Alembic to resolve a newer revision."""
    calls = []
    monkeypatch.setattr(Database, "migrate", lambda self: calls.append("migrate"))
    settings = Settings(
        agent_key=SecretStr(_KEY),
        database_url=SecretStr(TEST_DATABASE_URL),
        skip_database_migrations=should_skip,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").status_code == 200

    assert calls == ([] if should_skip else ["migrate"])
