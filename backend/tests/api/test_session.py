import os
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from app.adapters.clock import SystemClock
from app.main import create_app
from app.services.session_service import SESSION_TTL

_PASSWORD = os.environ["MAIN_USER_PASSWORD"]
_SESSION = "/api/v1/session"
_MAIN_USER_ROUTE = "/api/v1/agents"


def _client() -> TestClient:
    return TestClient(create_app(), base_url="https://junction.anvik.fi")


def test_login_sets_a_cookie_scripts_cannot_read() -> None:
    """HttpOnly stops a script from stealing the session. Lax stops a cross site approve."""
    response = _client().post(_SESSION, json={"password": _PASSWORD})

    assert response.status_code == HTTPStatus.NO_CONTENT
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Path=/api" in cookie


def test_session_opens_main_user_routes() -> None:
    """501 means the session check passed and the stub service ran."""
    client = _client()
    client.post(_SESSION, json={"password": _PASSWORD})

    response = client.get(_MAIN_USER_ROUTE)

    assert response.status_code == HTTPStatus.NOT_IMPLEMENTED


def test_wrong_password_gets_no_cookie() -> None:
    client = _client()

    response = client.post(_SESSION, json={"password": "guess"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert "set-cookie" not in response.headers
    assert client.get(_MAIN_USER_ROUTE).status_code == HTTPStatus.UNAUTHORIZED


def test_logout_closes_main_user_routes() -> None:
    client = _client()
    client.post(_SESSION, json={"password": _PASSWORD})
    token = client.cookies.get("valtuus_session")

    response = client.delete(_SESSION)

    assert response.status_code == HTTPStatus.NO_CONTENT
    # The server must forget the token, so a copied cookie stops working too.
    client.cookies.set("valtuus_session", token, domain="junction.anvik.fi", path="/api")
    assert client.get(_MAIN_USER_ROUTE).status_code == HTTPStatus.UNAUTHORIZED


def test_expired_cookie_closes_main_user_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser drops the cookie at Max-Age, but a copied cookie must stop working too."""
    client = _client()
    client.post(_SESSION, json={"password": _PASSWORD})
    later = SystemClock().now() + SESSION_TTL

    monkeypatch.setattr(SystemClock, "now", lambda self: later)

    assert client.get(_MAIN_USER_ROUTE).status_code == HTTPStatus.UNAUTHORIZED
