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
    cart_details_response,
    cart_response,
    mandate_response,
    offer_response,
    order_confirmation,
    order_response,
    search_response,
)
from app.api.schemas.audit import AuditResponse
from app.api.schemas.carts import (
    CartDetailsResponse,
    CartRequest,
    CartResponse,
    RevisionRequest,
)
from app.api.schemas.catalog import SearchRequest, SearchResponse
from app.api.schemas.common import CartRevisionValue, ErrorBody, IdempotencyKeyValue
from app.api.schemas.mandate import MandateResponse
from app.api.schemas.offers import OfferRequest, OfferResponse
from app.api.schemas.orders import OrderConfirmation
from app.domain.agent_key import AgentKey
from app.domain.catalog_response import HINT_CODE_DESCRIPTION
from app.domain.catalog_search import ATTRIBUTE_DESCRIPTION, QUERY_RULE
from app.domain.enums import AgentScope
from app.domain.errors import GatewayError
from app.services.decision_waiter import HOLD_SECONDS

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
        raise ToolError(ErrorBody.of(exc).model_dump_json(exclude_none=True)) from exc


def _add_cart_change_tools(server: MCPServer, services: Services, public_url: str) -> None:
    @server.tool()
    def revise_cart(
        cart_id: str,
        request: RevisionRequest,
        idempotency_key: IdempotencyKeyValue,
        ctx: Context,
    ) -> CartResponse:
        """Replace all lines of an AUTO or PENDING_APPROVAL cart. The policy runs again, so the
        result can be AUTO, PENDING_APPROVAL or DENIED.

        Send base_revision from your last get_cart. On a 409, follow next_step: for a closed
        cart or a changed revision, read get_cart and send the change on the current revision.
        PENDING_APPROVAL: give the buyer approve_url in this reply.
        """
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            cart = services.carts.revise_cart(
                agent,
                cart_id,
                request.base_revision,
                request.to_domain(),
                idempotency_key,
            )
            return cart_response(cart, public_url)

    @server.tool()
    def withdraw_cart(cart_id: str, ctx: Context) -> CartResponse:
        """Withdraw an AUTO or PENDING_APPROVAL cart that the buyer no longer wants.

        WITHDRAWN is final. The main user can no longer approve it. Other states return 409,
        so after a lost reply read get_cart: WITHDRAWN means the first call worked.
        """
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            return cart_response(services.carts.withdraw_cart(agent, cart_id), public_url)


def _add_wait_tool(server: MCPServer, services: Services, public_url: str) -> None:
    @server.tool(
        description=(
            "Wait while the main user decides on a PENDING_APPROVAL cart. You need no timer. "
            "Send the revision of your last read. It returns as soon as the state or the "
            "revision changes, or current_decision becomes AUTO, else after about "
            f"{HOLD_SECONDS:.0f} seconds with the cart still pending: then call it again. "
            "Each status line repeats approve_url."
        )
    )
    async def wait_for_decision(
        cart_id: str,
        revision: CartRevisionValue,
        ctx: Context,
    ) -> CartDetailsResponse:
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            details = await services.decisions.wait(agent.buyer_id, cart_id, revision)
            return cart_details_response(details, public_url)


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
            "Ask the buyer about choices and missing_fields in one question; search again with "
            "the chosen codes in required_attributes and the others in declined_attributes. "
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
        On-time products prioritize the mandate's preferred brands, then stock and price.
        A brand outside the mandate's preference requires human approval.
        Rejected products include a reason: expired cutoff, unavailable, no price, or no size
        for L/KG. PCS needs no size. Stock amounts >= 999999 mean unknown; 0 is unavailable.
        UPSTREAM_UNAVAILABLE: follow next_step and wait the stated seconds before retrying.
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
        """Make a cart from offer lines. The gateway decides AUTO, HUMAN or DENY.

        PENDING_APPROVAL: follow next_step. Give the buyer approve_url in this reply.
        """
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            cart = services.carts.create_cart(agent, request.to_domain(), idempotency_key)
            return cart_response(cart, public_url)

    @server.tool()
    def get_cart(cart_id: str, ctx: Context) -> CartDetailsResponse:
        """The current cart, revision, revision_count and changes since revision N-1.
        To wait for the main user's decision, call wait_for_decision.

        PENDING_APPROVAL: repeat approve_url in each status line to the buyer.
        """
        with _error_body():
            agent = _agent(ctx, AgentScope.CART)
            return cart_details_response(
                services.carts.get_cart_details(agent.buyer_id, cart_id), public_url
            )

    _add_wait_tool(server, services, public_url)
    _add_cart_change_tools(server, services, public_url)

    @server.tool()
    def checkout(
        cart_id: str,
        revision: CartRevisionValue,
        idempotency_key: IdempotencyKeyValue,
        ctx: Context,
    ) -> OrderConfirmation:
        """Place the order of an AUTO cart, or of a pending cart with current_decision AUTO.

        A 409 means no new order: the cart is now pending, denied or expired, or it was ordered
        with another key, or the revision changed. Send the revision you reviewed. For a stale
        revision, read get_cart and review its current lines before checking out again.
        Send the same revision and idempotency_key on a retry to get the same order.
        """
        with _error_body():
            agent = _agent(ctx, AgentScope.CHECKOUT)
            return order_confirmation(
                services.orders.checkout(agent, cart_id, revision, idempotency_key)
            )

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
