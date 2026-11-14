import dataclasses
import os
from http import HTTPStatus

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from app.adapters.memory.repositories import InMemoryAgentKeyRepository
from app.domain.agent_key import hash_agent_key
from app.domain.enums import AgentKeyStatus
from app.main import create_app

# The URL agents register. The trailing slash avoids a redirect, which behind Caddy
# would point to http.
_MCP_URL = "/api/mcp/"
_PROTOCOL_VERSION = "2025-06-18"
_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": _PROTOCOL_VERSION,
}
_PING = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "ping",
        "arguments": {},
    },
}
_AGENT_KEY = os.environ["AGENT_KEY"]


def _call_ping(app: FastAPI, authorization: str | None) -> Response:
    headers = dict(_HEADERS)
    if authorization is not None:
        headers["Authorization"] = authorization

    # The context manager runs the lifespan, which starts the MCP session manager.
    with TestClient(app, base_url="https://junction.anvik.fi") as client:
        return client.post(_MCP_URL, json=_PING, headers=headers)


def _assert_unauthenticated(response: Response) -> None:
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"] == "UNAUTHENTICATED"


def test_ping_tool_returns_pong() -> None:
    """An outside agent must reach a tool on the public MCP URL."""
    response = _call_ping(create_app(), f"Bearer {_AGENT_KEY}")

    assert response.status_code == HTTPStatus.OK
    assert response.json()["result"]["structuredContent"] == {"result": "pong"}


def test_call_without_key_is_refused() -> None:
    """Without the check, anyone who knows the URL could order as hotel 1."""
    _assert_unauthenticated(_call_ping(create_app(), None))


def test_call_with_wrong_key_is_refused() -> None:
    _assert_unauthenticated(_call_ping(create_app(), "Bearer not-the-agent-key"))


def test_call_with_other_scheme_is_refused() -> None:
    _assert_unauthenticated(_call_ping(create_app(), f"Basic {_AGENT_KEY}"))


def test_call_with_revoked_key_is_refused(agent_keys: InMemoryAgentKeyRepository) -> None:
    """A revoked agent must be stopped on its next call."""
    app = create_app(agent_keys=agent_keys)
    seeded = agent_keys.by_hash(hash_agent_key(_AGENT_KEY))
    agent_keys.add(dataclasses.replace(seeded, status=AgentKeyStatus.REVOKED))

    _assert_unauthenticated(_call_ping(app, f"Bearer {_AGENT_KEY}"))
