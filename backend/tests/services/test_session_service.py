from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.memory.repositories import (
    InMemorySessionRepository,
    InMemoryUnitOfWork,
    InMemoryUserRepository,
)
from app.domain.agent_key import User
from app.domain.enums import UserRole
from app.domain.errors import UnauthenticatedError
from app.domain.session import hash_session_token
from app.services.session_service import SESSION_TTL, SessionService

_PASSWORD = "test-main-password"
_MAIN_USER = User(user_id="hotel-1-main", buyer_id="hotel-1", role=UserRole.MAIN_USER)


class _Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 14, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.at


def _service(
    clock: _Clock | None = None,
    sessions: InMemorySessionRepository | None = None,
    password: str = _PASSWORD,
) -> SessionService:
    users = InMemoryUserRepository()
    users.add(_MAIN_USER)
    return SessionService(
        users,
        sessions or InMemorySessionRepository(),
        clock or _Clock(),
        InMemoryUnitOfWork(),
        _MAIN_USER.user_id,
        password,
    )


def test_right_password_opens_a_session_for_the_main_user() -> None:
    service = _service()

    token = service.login(_PASSWORD)

    assert service.user_for(token) == _MAIN_USER


def test_wrong_password_is_refused() -> None:
    with pytest.raises(UnauthenticatedError):
        _service().login("guess")


@pytest.mark.parametrize("password", ["", "   ", "\n"])
def test_blank_password_setting_refuses_to_start(password: str) -> None:
    """With a blank password, a login with spaces would open the approve page."""
    with pytest.raises(ValueError, match="empty"):
        _service(password=password)


@pytest.mark.parametrize("token", ["", "forged"])
def test_missing_or_unknown_token_has_no_user(token: str) -> None:
    assert _service().user_for(token) is None


def test_store_holds_only_the_token_hash() -> None:
    """A leaked sessions table must not give a working cookie."""
    sessions = InMemorySessionRepository()
    token = _service(sessions=sessions).login(_PASSWORD)

    assert sessions.get(token) is None
    assert sessions.get(hash_session_token(token)) is not None


def test_session_ends_after_its_ttl() -> None:
    """A stolen cookie must not work for ever."""
    clock = _Clock()
    service = _service(clock)
    token = service.login(_PASSWORD)

    clock.at += SESSION_TTL - timedelta(seconds=1)
    assert service.user_for(token) == _MAIN_USER

    clock.at += timedelta(seconds=1)
    assert service.user_for(token) is None


def test_login_drops_expired_sessions() -> None:
    """Nobody logs out of every session, so the store must not grow for ever."""
    clock = _Clock()
    sessions = InMemorySessionRepository()
    service = _service(clock, sessions)
    old = service.login(_PASSWORD)

    clock.at += SESSION_TTL
    service.login(_PASSWORD)

    assert sessions.get(hash_session_token(old)) is None


def test_logout_ends_the_session() -> None:
    service = _service()
    token = service.login(_PASSWORD)

    service.logout(token)

    assert service.user_for(token) is None


def test_password_change_ends_old_sessions() -> None:
    """A restart with a new password must not keep sessions opened with the old one."""
    sessions = InMemorySessionRepository()
    token = _service(sessions=sessions).login(_PASSWORD)

    assert _service(sessions=sessions, password="a-new-password").user_for(token) is None
    assert _service(sessions=sessions).user_for(token) == _MAIN_USER


def test_store_holds_no_password() -> None:
    """A leaked sessions table must not give the password either."""
    sessions = InMemorySessionRepository()
    token = _service(sessions=sessions).login(_PASSWORD)

    stored = sessions.get(hash_session_token(token))

    assert stored is not None
    assert _PASSWORD not in repr(stored)
