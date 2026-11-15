"""Equivalents: a product Valio Aimo's own data names in place of one it cannot deliver."""

from decimal import Decimal

from app.domain.catalog import Allergens, Product
from app.domain.enums import AllergenStatus, AllergenType, SubstituteBasis
from app.domain.money import round_money
from app.domain.offer import Candidate, OfferQuery, Price, RejectedProduct, SubstituteFor
from app.domain.units import fits_request, price_per_unit


def is_equivalent(requested: Product, substitute: Product) -> bool:
    """Known and equal in full: contains, may contain and free from.

    A swap must not add an allergen or a trace, or drop a free from claim the buyer relied on.
    82 of the 250 pairs in the product data pass (2026-11-15), the demo pair 464306 to 465039
    among them.
    """
    if requested.allergens.status is not AllergenStatus.KNOWN:
        return False

    return _facts(requested.allergens) == _facts(substitute.allergens)


def _facts(allergens: Allergens) -> tuple[object, ...]:
    # Per type, not the dict: a row stored by an old image has no MAY_CONTAIN key at all.
    declared = tuple(allergens.declarations.get(kind, ()) for kind in AllergenType)
    return allergens.status, allergens.free_from, declared


def substitute_for(
    requested: Product,
    requested_price: Price | None,
    rejected: RejectedProduct,
    substitute: Candidate,
    query: OfferQuery,
) -> SubstituteFor:
    return SubstituteFor(
        product_id=requested.product_id,
        name=requested.name,
        basis=SubstituteBasis.VALIO_PAIR,
        reason_code=rejected.reason_code,
        reason_sentence=rejected.reason_sentence,
        price_difference_per_unit=_difference(requested, requested_price, substitute, query),
    )


def _difference(
    requested: Product,
    requested_price: Price | None,
    substitute: Candidate,
    query: OfferQuery,
) -> Decimal | None:
    # Per L or KG, not per sales unit: 75 of the 250 pairs differ in sales unit (2026-11-15).
    # 465039 is a 5 l box in place of the 1 l bottle 464306.
    if requested_price is None or not fits_request(requested.content_per_sales_unit, query.unit):
        return None

    return _comparison(substitute.price, substitute.product, query) - _comparison(
        requested_price, requested, query
    )


def _comparison(price: Price, product: Product, query: OfferQuery) -> Decimal:
    # Rounded like the line's comparison_price, so the shown prices and difference add up.
    return round_money(price_per_unit(price.unit_price, query.unit, product.content_per_sales_unit))
