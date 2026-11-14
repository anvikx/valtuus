from http import HTTPStatus
from typing import Literal

from fastapi import APIRouter, Request, Response

from app.api.deps import SESSION_COOKIE, MainUserDep, PublicUrlDep, ServicesDep, session_token
from app.api.errors import ERROR_RESPONSES
from app.api.schemas.session import LoginRequest, SessionUser
from app.services.session_service import SESSION_TTL

router = APIRouter(prefix="/v1/auth", tags=["auth"], responses=ERROR_RESPONSES)

# The cookie goes only to the backend, never to the static frontend files.
_COOKIE_PATH = "/api"
_LOGIN = """
Log in as the main user. The answer sets the session cookie that the main user routes need.

**Request:** `{"password": "..."}`

**Auth:** none. Agents do not log in.
"""
_LOGOUT = """
End the main user session and clear its cookie.

**Auth:** none. With no session it still answers 204.
"""
_ME = """
The user of the session cookie. The UI calls it to show the buyer and to find out it is signed out.

**Auth:** main user session. With no session it answers 401.
"""


def _cookie_flags(public_url: str) -> dict[str, bool | Literal["lax"]]:
    # Caddy ends TLS, so the backend sees plain HTTP. The public URL says if the browser uses
    # HTTPS. HttpOnly keeps the token from scripts, and Lax keeps it off cross site POSTs.
    return {
        "secure": public_url.startswith("https://"),
        "httponly": True,
        "samesite": "lax",
    }


@router.post("/login", status_code=HTTPStatus.NO_CONTENT, description=_LOGIN.strip())
def login(body: LoginRequest, public_url: PublicUrlDep, services: ServicesDep) -> Response:
    token = services.sessions.login(body.password)
    response = Response(status_code=HTTPStatus.NO_CONTENT)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        path=_COOKIE_PATH,
        **_cookie_flags(public_url),
    )
    return response


@router.post("/logout", status_code=HTTPStatus.NO_CONTENT, description=_LOGOUT.strip())
def logout(request: Request, public_url: PublicUrlDep, services: ServicesDep) -> Response:
    services.sessions.logout(session_token(request))
    response = Response(status_code=HTTPStatus.NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path=_COOKIE_PATH, **_cookie_flags(public_url))
    return response


@router.get("/me", description=_ME.strip())
def me(user: MainUserDep) -> SessionUser:
    return SessionUser(user_id=user.user_id, buyer_id=user.buyer_id, role=user.role)
