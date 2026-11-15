"""Valio pair substitutes: which products replace a requested product that cannot be delivered."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from app.domain.catalog import Product
from app.domain.enums import AllergenStatus, ReasonCode, SubstituteBasis, Unit
from app.domain.money import round_money
from app.domain.offer import (
    AvailabilitySnapshot,
    Candidate,
    OfferQuery,
    Price,
    RejectedProduct,
    SubstituteFor,
)
from app.domain.ranking import delivery_late_sentence
from app.domain.screening import screen
from app.domain.units import comparison_unit, fits_request, price_per_unit

Screened = Candidate | RejectedProduct


@dataclass(frozen=True)
class SubstitutePair:
    original: Product
    substitute: Product


@dataclass(frozen=True)
class _Cause:
    code: ReasonCode
    sentence: str


def is_safe_pair(original: Product, substitute: Product) -> bool:
    """True only when both allergen records are KNOWN and declare exactly the same.

    Checked 2026-11-15 on the 17,546 products: 250 Valio pairs, 129 with KNOWN allergens on
    both sides, 97 with equal CONTAINS and MAY_CONTAIN declarations, 82 when free_from must
    also match. Comparing `contains` alone also gives 97, but it would hide a MAY_CONTAIN
    that moved to CONTAINS, so the declarations are compared.
    """
    known = AllergenStatus.KNOWN
    if original.allergens.status is not known or substitute.allergens.status is not known:
        return False

    return original.allergens.declarations == substitute.allergens.declarations


def substitute_pairs(
    requested: Sequence[Product],
    find: Callable[[str], Product | None],
) -> tuple[SubstitutePair, ...]:
    """Safe Valio pairs in request order. A requested product is never a substitute."""
    requested_ids = {product.product_id for product in requested}
    pairs: list[SubstitutePair] = []
    for original in requested:
        for substitute_id in dict.fromkeys(original.substitute_ids):
            substitute = None if substitute_id in requested_ids else find(substitute_id)
            if substitute is not None and is_safe_pair(original, substitute):
                pairs.append(SubstitutePair(original, substitute))

    return tuple(pairs)


def select_substitutes(
    pairs: Sequence[SubstitutePair],
    screened: Mapping[str, Screened],
    prices: Mapping[str, Price],
    snapshot: AvailabilitySnapshot,
    query: OfferQuery,
    now: datetime,
) -> tuple[Candidate, ...]:
    """One candidate per substitute product, tied to the first original that needs it.

    A substitute that is rejected or late is dropped: the agent did not ask for it.
    """
    chosen: dict[str, Candidate] = {}
    for pair in pairs:
        substitute_id = pair.substitute.product_id
        cause = _cause(screened[pair.original.product_id], query)
        if cause is None or substitute_id in chosen:
            continue

        result = screen(
            pair.substitute,
            prices.get(substitute_id),
            snapshot.items.get(substitute_id),
            query,
            now,
        )
        if not _is_usable(result, query):
            continue

        difference = _price_difference(pair, result, prices.get(pair.original.product_id), query)
        origin = SubstituteFor(
            product_id=pair.original.product_id,
            name=pair.original.name,
            basis=SubstituteBasis.VALIO_PAIR,
            reason_code=cause.code,
            reason_sentence=cause.sentence,
            price_difference_per_unit=difference,
            per=comparison_unit(query.unit),
        )
        chosen[substitute_id] = replace(result, substitute_for=origin)

    return tuple(chosen.values())


def _cause(original: Screened, query: OfferQuery) -> _Cause | None:
    if isinstance(original, RejectedProduct):
        return _Cause(original.reason_code, original.reason_sentence)

    sentence = delivery_late_sentence(original.availability, query)
    if sentence is None:
        return None

    return _Cause(ReasonCode.DELIVERY_AFTER_DEADLINE, sentence)


def _is_usable(result: Screened, query: OfferQuery) -> bool:
    return (
        isinstance(result, Candidate) and delivery_late_sentence(result.availability, query) is None
    )


def _price_difference(
    pair: SubstitutePair,
    substitute: Candidate,
    original_price: Price | None,
    query: OfferQuery,
) -> Decimal | None:
    """Substitute minus original per comparison unit. None when the original has no basis."""
    original = pair.original
    if original_price is None or not fits_request(original.content_per_sales_unit, query.unit):
        return None

    return _comparison(substitute.product, substitute.price, query.unit) - _comparison(
        original, original_price, query.unit
    )


def _comparison(product: Product, price: Price, unit: Unit | None) -> Decimal:
    # Rounded like OfferLine.comparison_price, so the difference equals what the page shows.
    per_unit = price_per_unit(price.unit_price, unit, product.content_per_sales_unit)
    return round_money(per_unit)
