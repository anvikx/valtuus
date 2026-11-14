from decimal import Decimal

import pytest

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import Unit
from app.domain.money import round_money
from app.domain.units import price_per_unit, sales_units_needed

_ONE_LITRE = ContentPerSalesUnit(Decimal(1), Unit.L)
_FIVE_LITRE_BOX = ContentPerSalesUnit(Decimal(5), Unit.L)
_ONE_KILO = ContentPerSalesUnit(Decimal(1), Unit.KG)


@pytest.mark.parametrize(
    ("quantity", "unit", "content", "needed"),
    [
        pytest.param("12", Unit.L, _FIVE_LITRE_BOX, 3, id="12 L in a 5 x 1 l box is 3 boxes"),
        pytest.param("1000", Unit.L, _ONE_LITRE, 1000, id="run 1: 1000 L of 1 l is 1000"),
        pytest.param("4", Unit.PCS, None, 4, id="a piece is one sales unit"),
        pytest.param(None, Unit.L, _ONE_LITRE, 1, id="no quantity is one sales unit"),
    ],
)
def test_sales_units_cover_the_request(quantity, unit, content, needed) -> None:
    """A part of a sales unit cannot be ordered, so the need rounds up, never down."""
    amount = None if quantity is None else Decimal(quantity)

    assert sales_units_needed(amount, unit, content) == needed


def test_the_sort_uses_the_full_price_and_the_screen_rounds() -> None:
    """1.372 and 1.374 both show 1.37, but the cheaper one must still rank first."""
    per_litre = price_per_unit(Decimal("6.86"), Unit.L, _FIVE_LITRE_BOX)

    assert per_litre == Decimal("1.372")
    assert round_money(per_litre) == Decimal("1.37")


def test_a_price_per_litre_is_never_made_from_kilograms() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        price_per_unit(Decimal("2.00"), Unit.L, _ONE_KILO)
