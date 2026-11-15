from decimal import Decimal

import pytest

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import Unit
from app.domain.money import round_money
from app.domain.units import price_per_unit, quantity_delivered, sales_units_needed

_ONE_LITRE = ContentPerSalesUnit(Decimal(1), Unit.L)
_FIVE_LITRE_BOX = ContentPerSalesUnit(Decimal(5), Unit.L)
_ONE_KILO = ContentPerSalesUnit(Decimal(1), Unit.KG)
_TEN_PIECES = ContentPerSalesUnit(Decimal(10), Unit.PCS)
_UNKNOWN_UNIT = ContentPerSalesUnit(Decimal(6), None)


@pytest.mark.parametrize(
    ("quantity", "unit", "content", "needed"),
    [
        pytest.param("12", Unit.L, _FIVE_LITRE_BOX, 3, id="12 L in a 5 x 1 l box is 3 boxes"),
        pytest.param("1000", Unit.L, _ONE_LITRE, 1000, id="run 1: 1000 L of 1 l is 1000"),
        pytest.param("4", Unit.PCS, None, 4, id="a piece is one sales unit"),
        pytest.param("25", Unit.PCS, _TEN_PIECES, 3, id="25 pieces in packs of 10 is 3 packs"),
        pytest.param("4", Unit.PCS, _ONE_LITRE, 4, id="a litre pack is one piece"),
        pytest.param("4", None, _UNKNOWN_UNIT, 4, id="no unit counts sales units"),
        pytest.param(None, Unit.L, _ONE_LITRE, 1, id="no quantity is one sales unit"),
    ],
)
def test_sales_units_cover_the_request(quantity, unit, content, needed) -> None:
    """A part of a sales unit cannot be ordered, so the need rounds up, never down."""
    amount = None if quantity is None else Decimal(quantity)

    assert sales_units_needed(amount, unit, content) == needed


@pytest.mark.parametrize(
    ("quantity", "unit", "pack_size", "boxes", "delivered", "excess"),
    [
        pytest.param("1000", Unit.L, "5", 200, "1000", "0", id="1000-l-in-five-litre-boxes"),
        pytest.param("12", Unit.L, "5", 3, "15", "3", id="12-l-delivers-three-litres-over"),
        pytest.param("10", Unit.L, "5", 2, "10", "0", id="exact-multiple-no-extra-box"),
        pytest.param("9.999999", Unit.L, "5", 2, "10", "0.000001", id="below-full-box"),
        pytest.param("10.000001", Unit.L, "5", 3, "15", "4.999999", id="above-full-box"),
        pytest.param("0.1", Unit.L, "5", 1, "5", "4.9", id="small-request-one-full-box"),
        pytest.param("1000", Unit.L, "20", 50, "1000", "0", id="1000-l-in-two-times-10-l"),
        pytest.param("12", Unit.L, "20", 1, "20", "8", id="12-l-in-two-times-10-l"),
        pytest.param("40", Unit.L, "20", 2, "40", "0", id="two-exact-20-l-boxes"),
        pytest.param("41", Unit.L, "20", 3, "60", "19", id="round-up-20-l-boxes"),
        pytest.param("2.5", Unit.KG, "1", 3, "3", "0.5", id="kilograms-round-up"),
        pytest.param("25", Unit.PCS, "10", 3, "30", "5", id="pieces-round-up"),
        pytest.param("20", Unit.PCS, "10", 2, "20", "0", id="exact-piece-packs"),
    ],
)
def test_full_packs_and_excess(quantity, unit, pack_size, boxes, delivered, excess):
    """The buyer receives enough whole packs, with the surplus expressed in requested units."""
    requested = Decimal(quantity)
    content = ContentPerSalesUnit(Decimal(pack_size), unit)

    count = sales_units_needed(requested, unit, content)
    actual = quantity_delivered(count, unit, content)

    assert count == boxes
    assert actual == Decimal(delivered)
    assert actual - requested == Decimal(excess)


def test_the_sort_uses_the_full_price_and_the_screen_rounds() -> None:
    """1.372 and 1.374 both show 1.37, but the cheaper one must still rank first."""
    per_litre = price_per_unit(Decimal("6.86"), Unit.L, _FIVE_LITRE_BOX)

    assert per_litre == Decimal("1.372")
    assert round_money(per_litre) == Decimal("1.37")


def test_a_price_per_piece_divides_by_the_pieces_in_a_pack() -> None:
    """A pack of 10 at 3.00 must rank against a single piece at 0.40 per piece."""
    assert price_per_unit(Decimal("3.00"), Unit.PCS, _TEN_PIECES) == Decimal("0.3")


def test_a_price_per_litre_is_never_made_from_kilograms() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        price_per_unit(Decimal("2.00"), Unit.L, _ONE_KILO)
