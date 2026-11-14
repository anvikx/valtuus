from app.main import create_app

_API_PREFIX = "/api/"

# Agents look these up at fixed root paths, so they cannot move under /api.
# Keep in sync with the @well_known matcher in the Caddyfile.
_WELL_KNOWN_PATHS = frozenset(
    {
        "/.well-known/jwks.json",
        "/.well-known/agent-trade.json",
    },
)


def test_all_routes_use_api_prefix() -> None:
    """Caddy proxies only /api/* and the well-known files to the backend.

    A route outside them is unreachable in prod.
    """
    app = create_app()

    # FastAPI 0.162 lists an included router as one object with no path, so the router
    # routes come from the OpenAPI paths. The docs pages and the MCP mount keep a path.
    paths = set(app.openapi()["paths"]) | {
        route.path for route in app.routes if hasattr(route, "path")
    }
    outside = sorted(
        path for path in paths if not path.startswith(_API_PREFIX) and path not in _WELL_KNOWN_PATHS
    )

    assert outside == []
