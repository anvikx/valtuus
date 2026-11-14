"""MCP door for outside agents. Each tool calls the same service as its REST route."""

from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from app.api.deps import Services, check_scope
from app.api.results import (
    audit_response,
    cart_response,
    mandate_response,
    offer_response,
    order_confirmation,
    order_response,
    search_response,
)
from app.api.schemas.audit import AuditResponse
from app.api.schemas.carts import CartRequest, CartResponse
from app.api.schemas.catalog import SearchRequest, SearchResponse
from app.api.schemas.common import ErrorBody, IdempotencyKeyValue
from app.api.schemas.mandate import MandateResponse
from app.api.schemas.offers import OfferRequest, OfferResponse
from app.api.schemas.orders import OrderConfirmation
from app.domain.agent_key import AgentKey
from app.domain.catalog_response import HINT_CODE_DESCRIPTION
from app.domain.catalog_search import ATTRIBUTE_DESCRIPTION, QUERY_RULE
from app.domain.enums import AgentScope
from app.domain.errors import GatewayError

# DNS rebinding protection guards servers on localhost. This one is public behind
# Caddy, and the agent key check is its guard.
_TRANSPORT_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def _agent(ctx: Context, scope: AgentScope) -> AgentKey:
    # AgentKeyGuard put the caller here before the MCP app saw the request.
    agent_key: AgentKey = ctx.request_context.request.state.agent_key
    check_scope(agent_key, scope)
    return agent_key


@contextmanager
def _error_body() -> Iterator[None]:
    """The agent gets the same error body as on REST. Other errors stay on the server."""
    try:
        yield
    except GatewayError as exc:
        body = ErrorBody(error=exc.code, message=exc.message, next_step=exc.next_step)
        raise ToolError(body.model_dump_json()) from exc


def create_mcp_server(services: Services, public_url: str) -> MCPServer:
    server = MCPServer(name="valtuus")

    @server.tool()
    def ping() -> str:
        """Check that the gateway answers."""
        return "pong"

    @server.tool(
        description=(
            "Search en/fi/sv names, including inside words, with accents folded. "
            f"Use {QUERY_RULE}. Negated names do not match. "
            "Returns the complete hint category, subject to the safety guard. "
            f"{HINT_CODE_DESCRIPTION} "
            "Inspect categories and examples to choose a type; use category to reach another. "
            "READY means complete for hint_category, not certainty about the intended type. "
            "No price or stock; call get_offers with all candidates and the returned request_id. "
            "VALIDATION_ERROR: correct the query or attribute codes. " + ATTRIBUTE_DESCRIPTION
        )
    )
    def search_products(request: SearchRequest, ctx: Context) -> SearchResponse:
        """Search the product file. No price and no stock.

        Send the returned request_id with get_offers for the same buyer request.
        """
        with _error_body():
            agent = _agent(ctx, AgentScope.CATALOG_READ)
            return search_response(services.catalog.search(agent, request.to_domain()))

    @server.tool()
    def get_offers(request: OfferRequest, ctx: Context) -> OfferResponse:
        """Live price and stock for chosen products, ranked by the mandate.

        Send request_id from search_products, so the audit trail shows the search.
        """
        with _error_body():
            agent = _agent(ctx, AgentScope.OFFER)
            return offer_response(services.offers.get_offers(agent, request.to_domain()))

    @server.tool()
    def create_cart(
        request: CartRequest,
        idempotency_key: IdempotencyKeyValue,
        ctx: Context,
    ) -> CartResponse:
        """Make a cart from offer lines. The gateway decides AUTO, HUMAN or DENY."""
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            cart = services.carts.create_cart(agent, request.to_domain(), idempotency_key)
            return cart_response(cart, public_url)

    @server.tool()
    def get_cart(cart_id: str, ctx: Context) -> CartResponse:
        """The cart and its current state. Poll it while the main user decides."""
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            return cart_response(services.carts.get_cart(agent.buyer_id, cart_id), public_url)

    @server.tool()
    def checkout(
        cart_id: str,
        idempotency_key: IdempotencyKeyValue,
        ctx: Context,
    ) -> OrderConfirmation:
        """Place the order of an AUTO cart, or of a pending cart with current_decision AUTO.

        A 409 means no new order: the cart is now pending, denied or expired, or it was ordered
        with another key. get_cart says why.
        Send the same idempotency_key on a retry to get the same order.
        """
        with _error_body():
            agent = _agent(ctx, AgentScope.CHECKOUT)
            return order_confirmation(services.orders.checkout(agent, cart_id, idempotency_key))

    @server.tool()
    def get_order(order_id: str, ctx: Context) -> OrderConfirmation:
        """A placed order."""
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            return order_response(services.orders.get_order(agent.buyer_id, order_id))

    @server.tool()
    def get_mandate(ctx: Context) -> MandateResponse:
        """The buyer's rules and the gateway time. Read it before a search."""
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            return mandate_response(services.mandates, services.mandates.get(agent.buyer_id))

    @server.tool()
    def get_audit(cart_id: str, ctx: Context) -> AuditResponse:
        """The audit trail of one cart."""
        with _error_body():
            agent = _agent(ctx, AgentScope.AUDIT_READ)
            return audit_response(cart_id, services.audit.for_cart(agent.buyer_id, cart_id))

    return server


def build_mcp_app(server: MCPServer) -> Starlette:
    # Stateless JSON: one worker, no session survives a deploy restart anyway.
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=_TRANSPORT_SECURITY,
    )
