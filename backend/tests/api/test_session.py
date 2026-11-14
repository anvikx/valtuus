import os
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from app.adapters.clock import SystemClock
from app.main import create_app
from app.services.seed import DEMO_BUYER_ID, DEMO_MAIN_USER_ID
from app.services.session_service import SESSION_TTL

_PASSWORD = os.environ["MAIN_USER_PASSWORD"]
_LOGIN = "/api/v1/auth/login"
_LOGOUT = "/api/v1/auth/logout"
_ME = "/api/v1/auth/me"
_MAIN_USER_ROUTE = "/api/v1/agents"


def _client() -> TestClient:
    return TestClient(create_app(), base_url="https://junction.anvik.fi")


def test_login_sets_a_cookie_scripts_cannot_read() -> None:
    """HttpOnly stops a script from stealing the session. Lax stops a cross site approve."""
    response = _client().post(_LOGIN, json={"password": _PASSWORD})

    assert response.status_code == HTTPStatus.NO_CONTENT
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Path=/api" in cookie


def test_session_opens_main_user_routes() -> None:
    """The main user has no agent key, so the session alone must open the permissions page."""
    client = _client()
    client.post(_LOGIN, json={"password": _PASSWORD})

    response = client.get(_MAIN_USER_ROUTE)

    assert response.status_code == HTTPStatus.OK


def test_session_opens_the_audit_trail() -> None:
    """The approve page shows the cart's audit trail to the main user, who has no agent key."""
    client = _client()
    client.post(_LOGIN, json={"password": _PASSWORD})

    response = client.get("/api/v1/audit/c_1")

    assert response.status_code not in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}


def test_wrong_password_gets_no_cookie() -> None:
    client = _client()

    response = client.post(_LOGIN, json={"password": "guess"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert "set-cookie" not in response.headers
    assert client.get(_MAIN_USER_ROUTE).status_code == HTTPStatus.UNAUTHORIZED


def test_logout_closes_main_user_routes() -> None:
    client = _client()
    client.post(_LOGIN, json={"password": _PASSWORD})
    token = client.cookies.get("valtuus_session")

    response = client.post(_LOGOUT)

    assert response.status_code == HTTPStatus.NO_CONTENT
    # The server must forget the token, so a copied cookie stops working too.
    client.cookies.set("valtuus_session", token, domain="junction.anvik.fi", path="/api")
    assert client.get(_MAIN_USER_ROUTE).status_code == HTTPStatus.UNAUTHORIZED


def test_me_names_the_signed_in_user() -> None:
    """The UI shows the buyer and learns it is signed out from this route, not from a cart 401."""
    client = _client()
    assert client.get(_ME).status_code == HTTPStatus.UNAUTHORIZED

    client.post(_LOGIN, json={"password": _PASSWORD})
    response = client.get(_ME)

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "user_id": DEMO_MAIN_USER_ID,
        "buyer_id": DEMO_BUYER_ID,
        "role": "MAIN_USER",
    }

    client.post(_LOGOUT)
    assert client.get(_ME).status_code == HTTPStatus.UNAUTHORIZED


def test_expired_cookie_closes_main_user_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser drops the cookie at Max-Age, but a copied cookie must stop working too."""
    client = _client()
    client.post(_LOGIN, json={"password": _PASSWORD})
    later = SystemClock().now() + SESSION_TTL

    monkeypatch.setattr(SystemClock, "now", lambda self: later)

    assert client.get(_MAIN_USER_ROUTE).status_code == HTTPStatus.UNAUTHORIZED
