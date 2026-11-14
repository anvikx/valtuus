from http import HTTPStatus

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import install_error_handlers
from app.domain.errors import UpstreamRateLimitedError


def test_a_rate_limit_tells_the_agent_when_to_retry() -> None:
    """A retry inside the Valio Aimo pause only extends it, so the agent must wait N seconds."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/paused")
    def paused() -> None:
        raise UpstreamRateLimitedError(20)

    response = TestClient(app).get("/paused")

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.headers["Retry-After"] == "20"
    assert response.json() == {
        "error": "UPSTREAM_UNAVAILABLE",
        "message": "The Valio Aimo price or stock service paused our calls.",
        "next_step": "Try again in 20 seconds.",
    }
