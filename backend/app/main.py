from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.memory import (
    InMemoryAgentKeyRepository,
    InMemoryMandateRepository,
    InMemoryUserRepository,
)
from app.api import health
from app.api.mcp_server import build_mcp_app, create_mcp_server
from app.config import Settings
from app.services.seed import seed_demo

# Caddy routes /api/* to the backend, so every route must live under this prefix.
_API_PREFIX = "/api"
_MCP_PATH = f"{_API_PREFIX}/mcp"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    mandates = InMemoryMandateRepository()
    agent_keys = InMemoryAgentKeyRepository()
    users = InMemoryUserRepository()
    seed_demo(
        mandates,
        agent_keys,
        users,
        agent_key=settings.agent_key.get_secret_value(),
    )

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
    app.state.mandates = mandates
    app.state.agent_keys = agent_keys
    app.state.users = users
    return app


app = create_app()
