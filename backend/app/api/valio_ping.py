"""Temporary step 0 check that the server reaches the Valio mock API. Remove after the check."""

import urllib.error
import urllib.request
from http import HTTPStatus

from fastapi import APIRouter, Response

from app.config import Settings

router = APIRouter()

_TIMEOUT_SECONDS = 10


@router.get("/debug/valio-ping")
def get_valio_ping(response: Response) -> dict[str, str]:
    # Returns only ok or failed, never the key or the upstream body.
    settings = Settings()
    request = urllib.request.Request(
        f"{settings.valio_base_url}/api/ping",
        headers={"X-API-Key": settings.valio_api_key.get_secret_value()},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as upstream:
            is_ok = upstream.status == HTTPStatus.OK
    except (urllib.error.URLError, TimeoutError):
        is_ok = False

    if not is_ok:
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
        return {"result": "failed"}

    return {"result": "ok"}
