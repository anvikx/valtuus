import json
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from app.api.schemas.carts import CartRequest, CartResponse
from app.api.schemas.catalog import ContentPerSalesUnit, SearchResponse
from app.api.schemas.mandate import MandateResponse, MandateUpdateRequest
from app.api.schemas.offers import OfferResponse
from app.api.schemas.orders import OrderConfirmation
from app.domain.enums import Unit

_INTERPRETED = {
    "query": "milk",
    "required_attributes": ["FREE_FROM_LACTOSE"],
    "quantity": 1000,
    "unit": "L",
    "deliver_by": "2026-11-16",
    "preferred_brands": [],
}
_ALLERGENS = {"status": "KNOWN", "contains": ["AM"], "free_from": []}

_SEARCH = {
    "hint_category": "10400",
    "understood": {**_INTERPRETED, "category": None, "declined_attributes": ["LOW_FAT"]},
    "missing_fields": [],
    "choices": [{"attribute": "EU_ORGANIC_FARMING", "hits": 11}],
    "total_hits": 1,
    "categories": [
        {"category": "10400", "hits": 1, "examples": ["Valio Arki Eila 1 l"], "in_list": True}
    ],
    "hint": {
        "code": "READY",
        "sentence": "The list has every product of this type. Call get_offers with all candidates.",
    },
    "candidates": [
        {
            "product_id": "464306",
            "gtin": "6408430000258",
            "name": "Valio Arki Eila 1 l",
            "match": "WHOLE_WORD",
            "brand": "Valio",
            "sales_unit": "ST",
            "content_per_sales_unit": {"value": 1, "unit": "L"},
            "sales_units_needed": 1000,
            "quantity_delivered": 1000,
            "quantity_over_request": 0,
            "attributes": ["FREE_FROM_LACTOSE"],
            "allergens": _ALLERGENS,
            "country_of_origin": "FI",
            "labels": [],
            "is_substitute_for": None,
        },
    ],
    "excluded": [{"product_id": "465039", "reason_code": "MISSING_ATTRIBUTE"}],
    "request_id": "r_0123456789abcdef0123456789abcdef",
}

_OFFER = {
    "offer_id": "o_1",
    "issuer": "Valio Aimo (mock)",
    "issued_at": "2026-11-14T10:00:00+02:00",
    "source_time": "2026-11-14T10:00:01+02:00",
    "valid_until": "2026-11-14T10:15:00+02:00",
    "requested": {"quantity": 1000, "unit": "L", "deliver_by": "2026-11-16"},
    "lines": [
        {
            "rank": 1,
            "tier": "BEST",
            "product_id": "464306",
            "gtin": "6408430000258",
            "name": "Valio Arki Eila 1 l",
            "brand": "Valio",
            "country_of_origin": "FI",
            "labels": [],
            "allergens": _ALLERGENS,
            "delivery_reliability": None,
            "co2_kg_per_kg": None,
            "sales_units_needed": 1000,
            "unit_price": "1.01",
            "currency": "EUR",
            "vat_rate": "13.5",
            "comparison_price": {"value": "1.01", "per": "L"},
            "price_valid_from": "2026-11-01",
            "price_valid_to": "2026-12-31",
            "stock_model": "STOCK",
            "available_qty": None,
            "available_date": "2026-11-16",
            "closing_time": "2026-11-15T17:00:00+02:00",
            "line_total": "1010.00",
            "max_auto_qty": 495,
            "substitute_for": None,
            "reason_codes": [],
            "reason_sentences": [],
        },
    ],
    "proposed_split": None,
    "rejected": [
        {
            "product_id": "465039",
            "name": "Valio Eila 1 l",
            "reason_code": "CUTOFF_PASSED",
            "reason_sentence": "The order deadline was Thu 12 Nov 15:00.",
            "closing_time": "2026-11-12T15:00:00+02:00",
        },
    ],
    "signature": None,
    "request_id": "r_0123456789abcdef0123456789abcdef",
}

_CART = {
    "cart_id": "c_1",
    "state": "PENDING_APPROVAL",
    "decision": "HUMAN",
    "reason_codes": ["OVER_AUTO_LIMIT"],
    "reason_sentences": ["1,010.00 EUR is over the 500.00 EUR limit."],
    "current_decision": "HUMAN",
    "current_reason_codes": ["OVER_AUTO_LIMIT"],
    "request_text": "I need 1,000 litres of lactose-free milk by Monday",
    "clarifications": [],
    "interpreted_request": _INTERPRETED,
    "lines": [
        {
            "offer_id": "o_1",
            "product_id": "464306",
            "name": "Valio Arki Eila 1 l",
            "qty": 1000,
            "unit_price": "1.01",
            "line_total": "1010.00",
            "delivery_date": "2026-11-16",
            "closing_time": "2026-11-15T17:00:00+02:00",
            "decision": "AUTO",
            "substitute_for": None,
            "reason_codes": [],
            "reason_sentences": [],
        },
    ],
    "total_ex_vat": "1010.00",
    "currency": "EUR",
    "mandate_version": 1,
    "valid_until": "2026-11-14T10:15:00+02:00",
    "approve_before": "2026-11-15T17:00:00+02:00",
    "duplicate_of_order_id": None,
    "delivery_day_total_ex_vat": "1010.00",
    "order_id": None,
    "previous_reject_reason": None,
    "decided_by": None,
    "decided_at": None,
    "reject_reason": None,
    "approve_url": "https://junction.anvik.fi/carts/c_1",
    "next_step": "Give the buyer this link now: https://junction.anvik.fi/carts/c_1.",
}

_ORDER = {
    "order_id": "ord_1",
    "cart_id": "c_1",
    "buyer_id": "hotel-1",
    "status": "CONFIRMED",
    "ledger": "PROTOTYPE",
    "lines": [
        {
            "product_id": "464306",
            "gtin": "6408430000258",
            "name": "Valio Arki Eila 1 l",
            "qty": 1000,
            "unit_price": "1.01",
            "line_total": "1010.00",
            "delivery_date": "2026-11-16",
            "substitute_for": None,
        },
    ],
    "total_ex_vat": "1010.00",
    "currency": "EUR",
    "placed_at": "2026-11-14T10:05:00+02:00",
    "placed_by": "claude-code (agent)",
    "approved_by": "main user of hotel-1",
    "offer_ids": ["o_1"],
    "mandate_version": 1,
    "issuer": "Valio Aimo (mock)",
    "signature": None,
}

_MANDATE = {
    "mandate": {
        "buyer_id": "hotel-1",
        "version": 1,
        "max_auto_order_value": "500.00",
        "max_auto_value_per_delivery_date": "500.00",
        "max_line_value": None,
        "required_attributes": [],
        "forbidden_allergens": [],
        "allergen_unknown_policy": "HUMAN",
        "preferred_brands": [],
        "ranking_weights": {"price": 1.0, "reliability": 0.0, "co2": 0.0},
        "can_auto_order": False,
        "summary": ["This agent may place orders up to 500.00 EUR per order."],
    },
    "now": "2026-11-14T10:00:00+02:00",
    "timezone": "Europe/Helsinki",
}


@pytest.mark.parametrize(
    ("model", "body"),
    [
        pytest.param(SearchResponse, _SEARCH, id="search"),
        pytest.param(OfferResponse, _OFFER, id="offer"),
        pytest.param(CartResponse, _CART, id="cart"),
        pytest.param(OrderConfirmation, _ORDER, id="order"),
        pytest.param(MandateResponse, _MANDATE, id="mandate"),
    ],
)
def test_body_round_trips(model: type[BaseModel], body: dict[str, object]) -> None:
    """Agents parse these bodies. Money must stay an exact string and quantities plain numbers."""
    parsed = model.model_validate_json(json.dumps(body))

    dumped = json.loads(parsed.model_dump_json())

    assert dumped == body


def test_fractional_quantity_is_a_number() -> None:
    """A 2.5 kg pack must reach the agent as 2.5, not as the string "2.5"."""
    content = ContentPerSalesUnit(value=Decimal("2.5"), unit=Unit.KG)

    dumped = json.loads(content.model_dump_json())

    assert dumped["value"] == 2.5


def test_cart_request_refuses_a_price() -> None:
    """Prices come from the stored offer. An agent that sends one must be refused, not ignored."""
    body = {
        "lines": [{"offer_id": "o_1", "product_id": "464306", "qty": 1000, "unit_price": "0.01"}],
        "request_text": "1,000 litres of lactose-free milk",
    }

    with pytest.raises(ValidationError, match="unit_price"):
        CartRequest.model_validate(body)


_LIMITS = ["max_auto_order_value", "max_auto_value_per_delivery_date"]


@pytest.mark.parametrize("field", _LIMITS)
@pytest.mark.parametrize("value", ["500.001", "0.005", "NaN", "Infinity", "-1"])
def test_mandate_limit_refuses_part_cents(field: str, value: str) -> None:
    """Totals are whole cents, so a limit of 500.001 would silently act as 500.00."""
    with pytest.raises(ValidationError, match=field):
        MandateUpdateRequest.model_validate({field: value})


@pytest.mark.parametrize("field", _LIMITS)
@pytest.mark.parametrize("value", ["1000000.01", "1E+30"])
def test_mandate_limit_has_an_upper_bound(field: str, value: str) -> None:
    """A typo of extra zeros would let the agent spend without any approval."""
    with pytest.raises(ValidationError, match=field):
        MandateUpdateRequest.model_validate({field: value})


@pytest.mark.parametrize("field", _LIMITS)
@pytest.mark.parametrize("value", ["500", "500.5", "500.50", "0", "1000000"])
def test_mandate_limit_takes_whole_cents(field: str, value: str) -> None:
    parsed = MandateUpdateRequest.model_validate({field: value})

    assert getattr(parsed, field) == Decimal(value)


@pytest.mark.parametrize("field", _LIMITS)
@pytest.mark.parametrize(
    ("value", "stored"), [("1e6", "1000000.00"), ("-0", "0.00"), ("5", "5.00")]
)
def test_mandate_limit_is_stored_as_plain_cents(field: str, value: str, stored: str) -> None:
    """The agent reads the limit back as text. "1E+6" or "-0" is not a price it can parse."""
    changes = MandateUpdateRequest.model_validate({field: value}).to_domain()

    assert str(getattr(changes, field)) == stored


def test_mandate_update_passes_the_automatic_order_switch() -> None:
    """False is a real change. Read as "missing", it would leave the agent ordering alone."""
    changes = MandateUpdateRequest.model_validate({"can_auto_order": False}).to_domain()

    assert changes.can_auto_order is False
