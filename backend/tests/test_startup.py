import dataclasses
import os
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import insert

from app.adapters.catalog_downloader import CatalogDownloader
from app.adapters.postgres.database import Database
from app.adapters.postgres.repositories import PostgresAgentKeyRepository
from app.adapters.postgres.tables import sessions
from app.adapters.product_store import ProductStore
from app.config import Settings
from app.domain.agent_key import hash_agent_key
from app.domain.enums import AgentKeyStatus
from app.domain.session import hash_session_token
from app.main import create_app
from tests.conftest import TEST_DATABASE_URL

_KEY = "test-agent-key-0123456789"
_BASE_URL = "https://junction.anvik.fi"


def _start_and_stop(settings: Settings) -> None:
    """The lifespan runs on enter and exit, so the engine closes as on a real stop."""
    with TestClient(create_app(settings)):
        pass


def test_app_refuses_to_start_without_agent_key() -> None:
    """With no key the agent door would have no working credential, so the deploy must fail."""
    settings = Settings(agent_key=SecretStr(""))

    with pytest.raises(ValueError, match="empty"):
        create_app(settings)


def test_app_refuses_to_start_without_main_user_password() -> None:
    """With no password, the deploy must fail, not open the approve page to an empty login."""
    settings = Settings(main_user_password=SecretStr(""))

    with pytest.raises(ValueError, match="empty"):
        create_app(settings)


@pytest.mark.parametrize("guard", [0, -1])
def test_settings_refuse_a_guard_that_returns_no_candidates(guard: int) -> None:
    """A guard below 1 empties every search while in_list still names a category."""
    with pytest.raises(ValueError, match="greater than 0"):
        Settings(candidate_guard=guard)


def test_refused_start_closes_the_database(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused start must not leave a pool of open connections behind."""
    closed: list[bool] = []
    monkeypatch.setattr(Database, "close", lambda self: closed.append(True))
    settings = Settings(
        database_url=SecretStr(TEST_DATABASE_URL),
        main_user_password=SecretStr(""),
    )

    with pytest.raises(ValueError, match="empty"):
        create_app(settings)

    assert closed == [True]


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
        assert client.get("/api/health").status_code == HTTPStatus.OK

    assert calls == ([] if should_skip else ["migrate"])


def test_restart_keeps_the_main_user_logged_in(database: Database) -> None:
    """A deploy must not log the main user out in the middle of an approval."""
    settings = Settings(
        agent_key=SecretStr(_KEY),
        database_url=SecretStr(TEST_DATABASE_URL),
    )
    with TestClient(create_app(settings), base_url=_BASE_URL) as client:
        client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})
        cookies = client.cookies

    with TestClient(create_app(settings), base_url=_BASE_URL, cookies=cookies) as client:
        # 501: the session check passed and the stub service ran.
        assert client.get("/api/v1/agents").status_code == HTTPStatus.NOT_IMPLEMENTED


def test_password_change_logs_the_main_user_out(database: Database) -> None:
    """After a leak the password is changed, so a session opened with the old one must end."""
    settings = Settings(
        agent_key=SecretStr(_KEY),
        database_url=SecretStr(TEST_DATABASE_URL),
    )
    with TestClient(create_app(settings), base_url=_BASE_URL) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"password": os.environ["MAIN_USER_PASSWORD"]},
        )
        # Without this, a failed login also ends in the 401 below and the test passes empty.
        assert login.status_code == HTTPStatus.NO_CONTENT
        cookies = client.cookies

    rotated = settings.model_copy(update={"main_user_password": SecretStr("a-new-password")})
    with TestClient(create_app(rotated), base_url=_BASE_URL, cookies=cookies) as client:
        assert client.get("/api/v1/agents").status_code == HTTPStatus.UNAUTHORIZED


def test_old_image_can_still_log_in(database: Database) -> None:
    """deploy.sh rolls back the image, not the schema. The old login insert has no tag."""
    old_token = "token-from-the-old-image"
    old_row = {
        "token_hash": hash_session_token(old_token),
        "user_id": "hotel-1-main",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }
    with database.transaction():
        database.writer().execute(insert(sessions).values(old_row))

    settings = Settings(agent_key=SecretStr(_KEY), database_url=SecretStr(TEST_DATABASE_URL))
    cookies = {"valtuus_session": old_token}
    with TestClient(create_app(settings), base_url=_BASE_URL, cookies=cookies) as client:
        # The row has no tag for the current password, so the new image refuses it.
        assert client.get("/api/v1/agents").status_code == HTTPStatus.UNAUTHORIZED
