from fastapi.routing import APIRoute

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

    # APIRoute skips FastAPI's own /docs and /openapi.json routes.
    outside = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and not route.path.startswith(_API_PREFIX)
        and route.path not in _WELL_KNOWN_PATHS
    ]

    assert outside == []
