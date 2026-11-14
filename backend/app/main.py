from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.api.mcp_server import build_mcp_app, create_mcp_server
from app.config import Settings

# Caddy routes /api/* to the backend, so every route must live under this prefix.
_API_PREFIX = "/api"
_MCP_PATH = f"{_API_PREFIX}/mcp"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    mcp_server = create_mcp_server()
    mcp_app = build_mcp_app(mcp_server)

    # Starlette does not run a mounted app's lifespan, so the MCP session manager
    # starts here.
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
    )
    app.include_router(
        health.router,
        prefix=_API_PREFIX,
    )
    app.mount(_MCP_PATH, mcp_app)
    return app


app = create_app()
