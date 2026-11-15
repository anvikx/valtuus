"""Rank by band (substitute, delivery group, preferred brand), then the mandate weighted score."""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from decimal import Decimal
from enum import IntEnum

from app.domain.constants import CURRENCY, UNKNOWN_STOCK_MARKER
from app.domain.enums import OfferTier, ReasonCode, StockModel
from app.domain.mandate import RankingWeights
from app.domain.money import line_total, round_money
from app.domain.offer import (
    Availability,
    Candidate,
    ComparisonPrice,
    OfferLine,
    OfferQuery,
    SubstituteFor,
)
from app.domain.reason_text import day_text, reason_sentence
from app.domain.units import comparison_unit, price_per_unit, sales_units_needed

_TIERS = (OfferTier.BEST, OfferTier.BETTER, OfferTier.GOOD)
_DOUBTFUL_STOCK = {ReasonCode.PARTIAL_AVAILABILITY, ReasonCode.STOCK_UNCONFIRMED}


class _Group(IntEnum):
    FULL = 0
    DOUBTFUL_STOCK = 1
    LATE = 2


_ZERO = Decimal(0)
_WORST = Decimal(1)

# Sort key before the score: substitutes last, then delivery group, then outside the brands.
_Band = tuple[bool, _Group, bool]


def rank_offer_lines(
    candidates: Iterable[Candidate],
    query: OfferQuery,
    weights: RankingWeights,
    substitutes: Sequence[tuple[Candidate, SubstituteFor]] = (),
) -> tuple[OfferLine, ...]:
    """Equal keys fall back to product_id, so the same data always gives the same order.

    Substitutes rank after every requested line: a person must approve each one, so a cheaper
    substitute must not lead a line the agent can order as asked.
    """
    entries = [
        *(_scored(candidate, query, None) for candidate in candidates),
        *(_scored(candidate, query, marked) for candidate, marked in substitutes),
    ]
    scores = _scores(entries, weights)
    # The raw price breaks score ties, because Decimal division can round two prices to one score.
    keyed = sorted(
        (band, score, per_unit, product_id, line)
        for (band, per_unit, product_id, line), score in zip(entries, scores, strict=True)
    )
    return tuple(
        replace(line, rank=rank, tier=_TIERS[rank - 1] if rank <= len(_TIERS) else None)
        for rank, (*_, line) in enumerate(keyed, start=1)
    )


def _scores(
    entries: Sequence[tuple[_Band, Decimal, str, OfferLine]],
    weights: RankingWeights,
) -> list[Decimal]:
    """One base for the whole offer, so a line scores the same in any band."""
    bands = [band for band, *_ in entries]
    lines = [line for *_, line in entries]
    price = _premiums([per_unit for _, per_unit, *_ in entries], bands)
    co2 = _premiums([line.co2_kg_per_kg for line in lines], bands)
    # Float weights go through str so 0.1 stays 0.1 and equal inputs give equal scores.
    w_price, w_reliability, w_co2 = (
        Decimal(str(w)) for w in (weights.price, weights.reliability, weights.co2)
    )
    return [
        w_price * price_premium + w_reliability * _reliability_cost(line) + w_co2 * co2_premium
        for line, price_premium, co2_premium in zip(lines, price, co2, strict=True)
    ]


def _reliability_cost(line: OfferLine) -> Decimal:
    # Fail closed: a product with no data never ranks above one with data.
    if line.delivery_reliability is None:
        return _WORST

    return _WORST - line.delivery_reliability


def _premiums(values: Sequence[Decimal | None], bands: Sequence[_Band]) -> list[Decimal]:
    """Share above the lowest known value: 1.01 against 1.00 is 0.01, the scale of reliability.

    Min-max scaling made a 1 cent gap count 1.0 and let a dearer line reorder two others.
    The base comes from the best band with data, so a cheap late line, substitute or other
    brand does not make price gaps count more between the lines ahead of it. A lower value in
    a worse band scores below 0, which keeps its order inside that band.
    None scores at least 1 and never better than the worst known value, so no data never wins.
    """
    known = [(band, value) for band, value in zip(bands, values, strict=True) if value is not None]
    if not known:
        return [_WORST] * len(values)

    best = min(band for band, _ in known)
    low = min(value for band, value in known if band == best)
    scored = {value: _premium(value, low) for _, value in known}
    missing = max(_WORST, *scored.values())
    return [missing if value is None else scored[value] for value in values]


def _premium(value: Decimal, low: Decimal) -> Decimal:
    # A share of 0 is undefined. Fail closed: any value above a zero minimum scores as no data.
    if low <= _ZERO:
        return _ZERO if value <= low else _WORST

    return (value - low) / low


def _scored(
    candidate: Candidate,
    query: OfferQuery,
    substitute_for: SubstituteFor | None,
) -> tuple[_Band, Decimal, str, OfferLine]:
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
        substitute_for=substitute_for,
        reason_codes=codes,
        reason_sentences=sentences,
    )
    group = _group(codes)
    preferred = {brand.casefold() for brand in query.preferred_brands}
    outside_preference = bool(preferred) and (product.brand or "").casefold() not in preferred
    # Following rank 1 must not exceed a preferred product's stock when another product
    # can fill the request. Brand preference only breaks ties within a stock group.
    band = (substitute_for is not None, group, outside_preference)
    return band, per_unit, product.product_id, line


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
    # Preserve the unconfirmed marker before it is collapsed to the same null count
    # as the larger "in stock" markers.
    if (
        availability.stock_model is not StockModel.STOCK
        or availability.amount == UNKNOWN_STOCK_MARKER
    ):
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
