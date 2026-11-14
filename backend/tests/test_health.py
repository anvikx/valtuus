from http import HTTPStatus

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok() -> None:
    """Deploy waits for this route to be healthy and rolls back when it is not."""
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}
