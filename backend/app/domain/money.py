from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from app.domain.constants import MONEY_DECIMALS

_CENT = Decimal(1).scaleb(-MONEY_DECIMALS)


def round_money(amount: Decimal) -> Decimal:
    """Round half up to cents. Every money value goes through here."""
    # A float has already lost the exact cents, so it is refused, not converted.
    if not isinstance(amount, Decimal):
        raise TypeError(f"money must be Decimal, got {type(amount).__name__}")

    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def line_total(qty: int, unit_price: Decimal) -> Decimal:
    return round_money(unit_price * qty)


def total_ex_vat(line_totals: Iterable[Decimal]) -> Decimal:
    """Sum of the rounded line totals. All limits compare this value."""
    return round_money(sum(line_totals, Decimal(0)))
