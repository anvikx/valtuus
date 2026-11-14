"""Domain results to response bodies. REST and MCP share them, so both doors answer alike."""

from collections.abc import Sequence
from dataclasses import asdict

from app.api.schemas.audit import AuditRecord as AuditRecordBody
from app.api.schemas.audit import AuditResponse
from app.api.schemas.carts import CartResponse
from app.api.schemas.catalog import SearchResponse
from app.api.schemas.mandate import Mandate as MandateBody
from app.api.schemas.mandate import MandateResponse
from app.api.schemas.offers import OfferResponse
from app.api.schemas.orders import OrderConfirmation
from app.domain.audit import AuditRecord
from app.domain.cart import Cart
from app.domain.catalog import SearchResult
from app.domain.constants import GATEWAY_TIMEZONE
from app.domain.errors import ConflictError
from app.domain.mandate import Mandate
from app.domain.offer import Offer
from app.domain.order import Order
from app.services.mandate_service import MandateService

# The frontend page where the main user approves or rejects a cart.
CART_PAGE_PATH = "/carts"


def search_response(result: SearchResult) -> SearchResponse:
    return SearchResponse.model_validate(result, from_attributes=True)


def offer_response(offer: Offer) -> OfferResponse:
    return OfferResponse.model_validate(offer, from_attributes=True)


def cart_response(cart: Cart, public_url: str) -> CartResponse:
    # The link is a web concern, so the domain cart does not carry it.
    approve_url = f"{public_url}{CART_PAGE_PATH}/{cart.cart_id}"
    return CartResponse.model_validate({**asdict(cart), "approve_url": approve_url})


def order_response(order: Order) -> OrderConfirmation:
    return OrderConfirmation.model_validate(order, from_attributes=True)


def order_confirmation(result: Order | Cart) -> OrderConfirmation:
    """A cart result means no order was placed, which the agent must read as a conflict."""
    if isinstance(result, Order):
        return order_response(result)

    raise ConflictError(
        " ".join(result.reason_sentences) or f"The cart is {result.state}.",
        "Read the cart with get_cart for its state and the next step.",
    )


def mandate_response(mandates: MandateService, mandate: Mandate) -> MandateResponse:
    body = MandateBody.model_validate({**asdict(mandate), "summary": mandates.summary(mandate)})
    return MandateResponse(mandate=body, now=mandates.now(), timezone=GATEWAY_TIMEZONE.key)


def audit_response(cart_id: str, records: Sequence[AuditRecord]) -> AuditResponse:
    bodies = [AuditRecordBody.model_validate(record, from_attributes=True) for record in records]
    return AuditResponse(cart_id=cart_id, records=bodies)
