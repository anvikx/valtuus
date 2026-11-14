from fastapi import FastAPI

from app.api import health
from app.config import Settings

# Caddy routes /api/* to the backend, so every route must live under this prefix.
_API_PREFIX = "/api"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(
        health.router,
        prefix=_API_PREFIX,
    )
    return app


app = create_app()
