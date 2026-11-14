from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.clock import SystemClock
from app.adapters.memory.repositories import (
    InMemoryAgentKeyRepository,
    InMemoryAuditRepository,
    InMemoryCartRepository,
    InMemoryIdempotencyRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryOrderRepository,
    InMemoryUnitOfWork,
    InMemoryUserRepository,
)
from app.adapters.product_store import ProductStore
from app.adapters.signer import NullSigner
from app.adapters.valio_client import ValioClient
from app.api import health
from app.api.deps import AgentKeyGuard, Services
from app.api.errors import install_error_handlers
from app.api.mcp_server import build_mcp_app, create_mcp_server
from app.api.v1 import agents, audit, carts, catalog, mandate, offers, orders
from app.config import Settings
from app.services.agent_key_service import AgentKeyService
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.catalog_service import CatalogService
from app.services.mandate_service import MandateService
from app.services.offer_service import OfferService
from app.services.order_service import OrderService
from app.services.seed import seed_demo

# Caddy routes /api/* to the backend, so every route must live under this prefix.
_API_PREFIX = "/api"
_MCP_PATH = f"{_API_PREFIX}/mcp"
_ROUTERS = (
    health.router,
    catalog.router,
    offers.router,
    carts.router,
    orders.router,
    mandate.router,
    agents.router,
    audit.router,
)


def _build_services(
    settings: Settings,
    mandate_repo: InMemoryMandateRepository,
    agent_key_repo: InMemoryAgentKeyRepository,
) -> Services:
    clock = SystemClock()
    signer = NullSigner()
    catalog_store = ProductStore(settings.data_dir)
    valio = ValioClient(settings.valio_base_url, settings.valio_api_key)
    offer_repo = InMemoryOfferRepository()
    cart_repo = InMemoryCartRepository()
    order_repo = InMemoryOrderRepository()
    idempotency_repo = InMemoryIdempotencyRepository()
    unit_of_work = InMemoryUnitOfWork()

    audit_service = AuditService(InMemoryAuditRepository(), clock)
    mandate_service = MandateService(
        mandate_repo,
        clock,
        audit_service,
        unit_of_work,
    )
    order_service = OrderService(
        cart_repo,
        order_repo,
        idempotency_repo,
        mandate_service,
        valio,
        signer,
        clock,
        audit_service,
        unit_of_work,
    )
    return Services(
        agent_keys=AgentKeyService(agent_key_repo),
        catalog=CatalogService(
            catalog_store,
            mandate_repo,
            audit_service,
        ),
        offers=OfferService(
            catalog_store,
            valio,
            offer_repo,
            signer,
            clock,
            audit_service,
        ),
        carts=CartService(
            offer_repo,
            cart_repo,
            order_repo,
            idempotency_repo,
            mandate_service,
            clock,
            audit_service,
            unit_of_work,
        ),
        orders=order_service,
        approvals=ApprovalService(
            cart_repo,
            order_service,
            mandate_service,
            clock,
            audit_service,
            unit_of_work,
        ),
        mandates=mandate_service,
        audit=audit_service,
    )


def create_app(
    settings: Settings | None = None,
    agent_keys: InMemoryAgentKeyRepository | None = None,
) -> FastAPI:
    """agent_keys lets a test change the seeded key without reaching into the app."""
    settings = settings or Settings()
    agent_keys = InMemoryAgentKeyRepository() if agent_keys is None else agent_keys
    mandates = InMemoryMandateRepository()
    users = InMemoryUserRepository()
    seed_demo(
        mandates,
        agent_keys,
        users,
        agent_key=settings.agent_key.get_secret_value(),
    )
    services = _build_services(settings, mandates, agent_keys)

    mcp_server = create_mcp_server(services, settings.public_url)
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
    install_error_handlers(app)
    for router in _ROUTERS:
        app.include_router(router, prefix=_API_PREFIX)
    app.mount(_MCP_PATH, AgentKeyGuard(mcp_app, services.agent_keys))
    app.state.services = services
    app.state.public_url = settings.public_url
    return app


app = create_app()
