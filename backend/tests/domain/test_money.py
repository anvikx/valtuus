from decimal import Decimal

import pytest

from app.domain.money import line_total, round_money, total_ex_vat


@pytest.mark.parametrize(
    ("qty", "unit_price", "expected"),
    [
        pytest.param(1000, "1.01", "1010.00", id="run-1-order"),
        pytest.param(7, "6.86", "48.02", id="float-would-drift"),
    ],
)
def test_line_total_is_exact(qty, unit_price, expected):
    """The total on the page, in the signed offer and against the limit must be the same cents."""
    total = line_total(qty, Decimal(unit_price))

    assert str(total) == expected


def test_round_money_rounds_half_up():
    """Half up is how a buyer checks a sum. Banker's rounding would give 0.00 here."""
    rounded = round_money(Decimal("0.005"))

    assert rounded == Decimal("0.01")


def test_round_money_refuses_float():
    """A float has already lost the cents, so no money value may enter as one."""
    with pytest.raises(TypeError):
        round_money(1.01)  # type: ignore[arg-type]


def test_total_ex_vat_sums_rounded_lines():
    """The limit check compares the same total that the buyer sees."""
    lines = [line_total(3, Decimal("0.335")), line_total(1, Decimal("0.335"))]

    total = total_ex_vat(lines)

    assert total == Decimal("1.35")
