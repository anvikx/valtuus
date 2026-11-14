from http import HTTPStatus

from fastapi.testclient import TestClient

from app.main import create_app

# The URL agents register. The trailing slash avoids a redirect, which behind Caddy
# would point to http.
_MCP_URL = "/api/mcp/"
_PROTOCOL_VERSION = "2025-06-18"
_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": _PROTOCOL_VERSION,
}


def test_ping_tool_returns_pong() -> None:
    """An outside agent must reach a tool on the public MCP URL."""
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "ping",
            "arguments": {},
        },
    }

    # The context manager runs the lifespan, which starts the MCP session manager.
    with TestClient(create_app(), base_url="https://junction.anvik.fi") as client:
        response = client.post(_MCP_URL, json=call, headers=_HEADERS)

    assert response.status_code == HTTPStatus.OK
    assert response.json()["result"]["structuredContent"] == {"result": "pong"}
