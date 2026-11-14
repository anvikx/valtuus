import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from pydantic import SecretStr

from app.adapters.catalog_downloader import CatalogDownloader
from app.adapters.clock import SystemClock
from app.adapters.memory.repositories import (
    InMemoryAgentKeyRepository,
    InMemoryAuditRepository,
    InMemoryCartRepository,
    InMemoryIdempotencyRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryOrderRepository,
    InMemorySessionRepository,
    InMemoryUnitOfWork,
    InMemoryUserRepository,
)
from app.adapters.postgres.catalog import PostgresCatalog
from app.adapters.postgres.database import Database
from app.adapters.postgres.repositories import (
    PostgresAgentKeyRepository,
    PostgresAuditRepository,
    PostgresCartRepository,
    PostgresIdempotencyRepository,
    PostgresMandateRepository,
    PostgresOfferRepository,
    PostgresOrderRepository,
    PostgresSessionRepository,
    PostgresUserRepository,
)
from app.adapters.product_store import ProductStore
from app.adapters.signer import NullSigner
from app.adapters.valio_client import ValioClient
from app.api import health
from app.api.deps import AgentKeyGuard, Services
from app.api.errors import install_error_handlers
from app.api.mcp_server import build_mcp_app, create_mcp_server
from app.api.v1 import agents, audit, carts, catalog, mandate, offers, orders, session
from app.config import Settings
from app.services.agent_key_service import AgentKeyService
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.catalog_service import CatalogService
from app.services.mandate_service import MandateService
from app.services.offer_service import OfferService
from app.services.order_service import OrderService
from app.services.ports.catalog import ProductCatalog
from app.services.ports.repositories import (
    AgentKeyRepository,
    AuditRepository,
    CartRepository,
    IdempotencyRepository,
    MandateRepository,
    OfferRepository,
    OrderRepository,
    SessionRepository,
    UserRepository,
)
from app.services.ports.unit_of_work import UnitOfWork
from app.services.seed import DEMO_MAIN_USER_ID, seed_demo
from app.services.session_service import SessionService

_logger = logging.getLogger(__name__)

# Caddy routes /api/* to the backend, so every route must live under this prefix.
_API_PREFIX = "/api"
_MCP_PATH = f"{_API_PREFIX}/mcp"
_DOCS_PATH = f"{_API_PREFIX}/docs"
_OPENAPI_PATH = f"{_API_PREFIX}/openapi.json"
# The first page a reader of /api/docs sees: the rules every call follows.
_API_DESCRIPTION = f"""
Lets outside AI agents buy Valio Aimo products within the buyer's mandate.

* **Auth:** an agent sends `Authorization: Bearer <agent key>`. Use **Authorize** to try a call.
  Routes marked *Main user* need the main user's session from `POST /api/v1/auth/login` instead.
* **Flow:** read the mandate, search, get offers, create a cart. Then check out an AUTO cart, or
  poll a HUMAN cart while the main user decides.
* **Retries:** create cart and checkout need an `Idempotency-Key` header. Send the same key again
  on a retry.
* **Money:** EUR ex VAT, as a decimal string such as `"12.50"`.
* **Errors:** every error has the body `{{error, message, next_step}}`. Follow `next_step`.
* **MCP:** the same operations are tools at `{_MCP_PATH}/`.
"""
_ROUTERS = (
    health.router,
    catalog.router,
    offers.router,
    carts.router,
    orders.router,
    mandate.router,
    agents.router,
    audit.router,
    session.router,
)


@dataclass(frozen=True)
class _Store:
    mandates: MandateRepository
    agent_keys: AgentKeyRepository
    users: UserRepository
    offers: OfferRepository
    carts: CartRepository
    orders: OrderRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository
    sessions: SessionRepository
    unit_of_work: UnitOfWork
    close: Callable[[], None]
    database: Database | None = None


def _memory_store() -> _Store:
    return _Store(
        mandates=InMemoryMandateRepository(),
        agent_keys=InMemoryAgentKeyRepository(),
        users=InMemoryUserRepository(),
        offers=InMemoryOfferRepository(),
        carts=InMemoryCartRepository(),
        orders=InMemoryOrderRepository(),
        audit=InMemoryAuditRepository(),
        idempotency=InMemoryIdempotencyRepository(),
        sessions=InMemorySessionRepository(),
        unit_of_work=InMemoryUnitOfWork(),
        close=lambda: None,
    )


def _postgres_store(url: SecretStr) -> _Store:
    database = Database.from_url(url)
    database.migrate()
    return _Store(
        mandates=PostgresMandateRepository(database),
        agent_keys=PostgresAgentKeyRepository(database),
        users=PostgresUserRepository(database),
        offers=PostgresOfferRepository(database),
        carts=PostgresCartRepository(database),
        orders=PostgresOrderRepository(database),
        audit=PostgresAuditRepository(database),
        idempotency=PostgresIdempotencyRepository(database),
        sessions=PostgresSessionRepository(database),
        unit_of_work=database,
        close=database.close,
        database=database,
    )


def _open_store(settings: Settings) -> _Store:
    if settings.database_url.get_secret_value():
        return _postgres_store(settings.database_url)

    _logger.warning("DATABASE_URL is empty: in-memory store, all data is lost on restart")
    return _memory_store()


def _build_services(settings: Settings, store: _Store, catalog_store: ProductCatalog) -> Services:
    clock = SystemClock()
    signer = NullSigner()
    valio = ValioClient(settings.valio_base_url, settings.valio_api_key)

    audit_service = AuditService(store.audit, clock)
    mandate_service = MandateService(
        store.mandates,
        clock,
        audit_service,
        store.unit_of_work,
    )
    order_service = OrderService(
        store.carts,
        store.orders,
        store.idempotency,
        mandate_service,
        valio,
        signer,
        clock,
        audit_service,
        store.unit_of_work,
    )
    return Services(
        agent_keys=AgentKeyService(store.agent_keys),
        catalog=CatalogService(
            catalog_store,
            store.mandates,
            audit_service,
        ),
        offers=OfferService(
            catalog_store,
            valio,
            store.offers,
            signer,
            clock,
            audit_service,
            store.unit_of_work,
            settings.candidate_guard,
        ),
        carts=CartService(
            store.offers,
            store.carts,
            store.orders,
            store.idempotency,
            mandate_service,
            clock,
            audit_service,
            store.unit_of_work,
        ),
        orders=order_service,
        approvals=ApprovalService(
            store.carts,
            order_service,
            mandate_service,
            clock,
            audit_service,
            store.unit_of_work,
        ),
        mandates=mandate_service,
        audit=audit_service,
        sessions=SessionService(
            store.users,
            store.sessions,
            clock,
            store.unit_of_work,
            DEMO_MAIN_USER_ID,
            settings.main_user_password.get_secret_value(),
        ),
    )


def create_app(
    settings: Settings | None = None,
    agent_keys: AgentKeyRepository | None = None,
) -> FastAPI:
    """agent_keys lets a test change the seeded key without reaching into the app."""
    settings = settings or Settings()
    store = _open_store(settings)
    if agent_keys is not None:
        store = dataclasses.replace(store, agent_keys=agent_keys)

    try:
        seed_demo(
            store.mandates,
            store.agent_keys,
            store.users,
            store.unit_of_work,
            agent_key=settings.agent_key.get_secret_value(),
        )
        loader = ProductStore(settings.data_dir)
        catalog_store = PostgresCatalog(store.database) if store.database else loader
        services = _build_services(settings, store, catalog_store)
    except Exception:
        store.close()
        raise

    mcp_server = create_mcp_server(services, settings.public_url)
    mcp_app = build_mcp_app(mcp_server)

    # Starlette does not run a mounted app's lifespan, so the MCP session manager
    # starts here.
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            downloader = CatalogDownloader(
                settings.valio_base_url, settings.valio_api_key, settings.data_dir
            )
            files = await asyncio.to_thread(downloader.download)
            await asyncio.to_thread(loader.load, files)
            if isinstance(catalog_store, PostgresCatalog):
                await asyncio.to_thread(catalog_store.replace, loader.products())
                loader.clear()
            async with mcp_server.session_manager.run():
                yield
        finally:
            store.close()

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        description=_API_DESCRIPTION,
        docs_url=_DOCS_PATH,
        openapi_url=_OPENAPI_PATH,
        # Agents authenticate with a Bearer key, not OAuth2, so Swagger needs no redirect page.
        swagger_ui_oauth2_redirect_url=None,
        redoc_url=None,
    )
    install_error_handlers(app)
    for router in _ROUTERS:
        app.include_router(router, prefix=_API_PREFIX)
    app.mount(_MCP_PATH, AgentKeyGuard(mcp_app, services.agent_keys))
    app.state.services = services
    app.state.public_url = settings.public_url
    return app


app = create_app()
