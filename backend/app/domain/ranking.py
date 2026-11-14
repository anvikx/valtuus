"""Tier 1 ranking: delivery group first, then the price per requested unit, lowest first."""

from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal
from enum import IntEnum

from app.domain.constants import CURRENCY, UNKNOWN_STOCK_MARKER
from app.domain.enums import OfferTier, ReasonCode, StockModel
from app.domain.money import line_total, round_money
from app.domain.offer import Availability, Candidate, ComparisonPrice, OfferLine, OfferQuery
from app.domain.reason_text import day_text, reason_sentence
from app.domain.units import comparison_unit, price_per_unit, sales_units_needed

_TIERS = (OfferTier.BEST, OfferTier.BETTER, OfferTier.GOOD)
_DOUBTFUL_STOCK = {ReasonCode.PARTIAL_AVAILABILITY, ReasonCode.STOCK_UNCONFIRMED}


class _Group(IntEnum):
    FULL = 0
    DOUBTFUL_STOCK = 1
    LATE = 2


def rank_offer_lines(candidates: Iterable[Candidate], query: OfferQuery) -> tuple[OfferLine, ...]:
    """Equal keys fall back to product_id, so the same data always gives the same order."""
    scored = sorted(_scored(candidate, query) for candidate in candidates)
    return tuple(
        replace(line, rank=rank, tier=_TIERS[rank - 1] if rank <= len(_TIERS) else None)
        for rank, (*_, line) in enumerate(scored, start=1)
    )


def _scored(candidate: Candidate, query: OfferQuery) -> tuple[_Group, Decimal, str, OfferLine]:
    product, price, availability = candidate.product, candidate.price, candidate.availability
    _require_screened(availability)

    content = product.content_per_sales_unit
    needed = sales_units_needed(query.quantity, query.unit, content)
    per_unit = price_per_unit(price.unit_price, query.unit, content)
    available_qty = counted_stock(availability)
    codes, sentences = _reasons(availability, available_qty, needed, query)
    line = OfferLine(
        rank=0,
        tier=None,
        product_id=product.product_id,
        gtin=product.gtin,
        name=product.name,
        brand=product.brand,
        country_of_origin=product.country_of_origin,
        labels=product.labels,
        allergens=product.allergens,
        delivery_reliability=product.delivery_reliability,
        co2_kg_per_kg=product.co2_kg_per_kg,
        sales_units_needed=needed,
        unit_price=price.unit_price,
        currency=CURRENCY,
        vat_rate=price.vat_rate,
        comparison_price=ComparisonPrice(round_money(per_unit), comparison_unit(query.unit)),
        price_valid_from=price.valid_from,
        price_valid_to=price.valid_to,
        stock_model=availability.stock_model,
        available_qty=available_qty,
        available_date=availability.available_date,
        closing_time=availability.closing_time,
        line_total=line_total(needed, price.unit_price),
        max_auto_qty=None,
        substitute_for=None,
        reason_codes=codes,
        reason_sentences=sentences,
    )
    return _group(codes), per_unit, product.product_id, line


def _require_screened(availability: Availability) -> None:
    # screen() rejects these. A None here would rank a product on a missing date or stock.
    if availability.available_date is None or availability.closing_time is None:
        raise ValueError(f"{availability.product_id} was not screened")

    if not availability.amount:
        raise ValueError(f"{availability.product_id} was not screened")


def counted_stock(availability: Availability) -> int | None:
    """A number only for a real STOCK count. 999999 or more means amount not known."""
    if availability.stock_model is not StockModel.STOCK:
        return None

    if availability.amount is None or availability.amount >= UNKNOWN_STOCK_MARKER:
        return None

    return availability.amount


def _reasons(
    availability: Availability,
    available_qty: int | None,
    needed: int,
    query: OfferQuery,
) -> tuple[tuple[ReasonCode, ...], tuple[str, ...]]:
    reasons: list[tuple[ReasonCode, str]] = []
    # A null logistic model is unknown stock, as for Terminal.
    if availability.stock_model is not StockModel.STOCK:
        code = ReasonCode.STOCK_UNCONFIRMED
        reasons.append((code, reason_sentence(code)))
    elif available_qty is not None and available_qty < needed:
        code = ReasonCode.PARTIAL_AVAILABILITY
        sentence = reason_sentence(code, available_qty=available_qty, needed_qty=needed)
        reasons.append((code, sentence))

    # No deliver_by asks for the earliest date, so nothing can be late.
    if query.deliver_by is not None and availability.available_date > query.deliver_by:
        code = ReasonCode.DELIVERY_AFTER_DEADLINE
        sentence = reason_sentence(
            code,
            available_date=day_text(availability.available_date),
            deliver_by=day_text(query.deliver_by),
        )
        reasons.append((code, sentence))

    return tuple(code for code, _ in reasons), tuple(sentence for _, sentence in reasons)


def _group(codes: tuple[ReasonCode, ...]) -> _Group:
    # Late and partial together is late: the date is the harder miss.
    if ReasonCode.DELIVERY_AFTER_DEADLINE in codes:
        return _Group.LATE

    if _DOUBTFUL_STOCK.intersection(codes):
        return _Group.DOUBTFUL_STOCK

    return _Group.FULL
