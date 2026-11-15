from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import ReasonCode, Unit
from app.domain.offer import ComparisonPrice, OfferLine, ProposedSplit, SplitLine
from app.domain.split import propose_split
from tests.adapters import samples
from tests.fakes.offer_data import MONDAY, ONE_LITRE, query

_ARLA_ID = "469363"
_ARLA_NAME = "Arla Semi skimmed milkdrink 1 L UHT lactose free Suomesta"
_VALIO_ID = "464306"
_VALIO_NAME = "Valio Hyvä suomalainen Arki® Eila® semi skimmed milk drink 1 l lactose free"
_PARTIAL = (ReasonCode.PARTIAL_AVAILABILITY,)
_OUTSIDE = (ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE,)
_LATE = (ReasonCode.DELIVERY_AFTER_DEADLINE,)


def _line(
    product_id: str,
    brand: str,
    *,
    name: str = "",
    price: str = "1.00",
    stock: int | None = None,
    needed: int = 1000,
    codes: tuple[ReasonCode, ...] = (),
    available_date: date = MONDAY,
    rank: int = 1,
) -> OfferLine:
    return replace(
        samples.offer().lines[0],
        product_id=product_id,
        name=name or f"Milk {product_id}",
        brand=brand,
        comparison_price=ComparisonPrice(Decimal(price), Unit.L),
        sales_units_needed=needed,
        available_qty=stock,
        available_date=available_date,
        rank=rank,
        reason_codes=codes,
        substitute_for=None,
    )


def _arla(stock: int = 384, price: str = "0.90") -> OfferLine:
    return _line(
        _ARLA_ID, "Arla", name=_ARLA_NAME, price=price, stock=stock, codes=_PARTIAL, rank=2
    )


def _valio(price: str = "1.01") -> OfferLine:
    return _line(_VALIO_ID, "Valio", name=_VALIO_NAME, price=price, rank=1)


def _contents(*lines: OfferLine) -> dict[str, ContentPerSalesUnit | None]:
    return {line.product_id: ONE_LITRE for line in lines}


def _split(*lines: OfferLine, brands: tuple[str, ...] = ("Arla",), **ask: object):
    return propose_split(lines, _contents(*lines), query(**ask), brands)


def test_run_3_takes_all_preferred_stock_and_fills_with_group_a() -> None:
    """Run 3: the buyer prefers Arla, 384 L exist, so the rest comes from the Valio line."""
    lines = (_valio(), _arla())

    split = _split(*lines)

    assert split == ProposedSplit(
        lines=(
            SplitLine(_ARLA_ID, 384, _PARTIAL),
            SplitLine(_VALIO_ID, 616, _OUTSIDE),
        ),
        unfilled_qty=0,
    )


def test_a_filler_of_a_preferred_brand_gets_no_substitute_code() -> None:
    """The code says the buyer's brand was left. A preferred brand filler leaves nothing."""
    lines = (_valio(), _arla())

    split = _split(*lines, brands=("Arla", "valio"))

    assert split is not None
    assert split.lines[1].reason_codes == ()


def test_the_brands_given_decide_which_line_is_short() -> None:
    """With Valio preferred, the short Arla line is not a preferred one, so no top up."""
    lines = (_valio(), _arla())

    split = _split(*lines, brands=("Valio",))

    # Valio is preferred and Arla is not: no preferred line is short, so rank 1 covers.
    assert split is None


def test_rest_is_converted_per_product_content() -> None:
    """616 L is 154 boxes of 4 l: a count in litres would order four times too much."""
    box = ContentPerSalesUnit(Decimal(4), Unit.L)
    arla = replace(_arla(stock=100), sales_units_needed=1000)
    valio = replace(_valio(), sales_units_needed=250)
    contents = {_ARLA_ID: ONE_LITRE, _VALIO_ID: box}

    split = propose_split((valio, arla), contents, query(), ("Arla",))

    assert split is not None
    assert split.lines[1] == SplitLine(_VALIO_ID, 225, _OUTSIDE)


def test_a_preferred_line_that_covers_the_request_needs_no_split() -> None:
    """Only a short preferred stock is topped up. Full stock is rank 1's job."""
    arla = _line(_ARLA_ID, "Arla", stock=1000)

    assert _split(_valio(), arla) is None


def test_no_group_a_line_takes_confirmed_stock_by_price() -> None:
    """Rule 1 needs a group A filler. Without one, stock lines are used cheapest first."""
    arla = _arla(stock=384, price="0.90")
    other = _line("400001", "Valio", price="0.95", stock=300, codes=_PARTIAL)

    split = _split(arla, other, brands=())

    assert split == ProposedSplit(
        lines=(SplitLine(_ARLA_ID, 384, _PARTIAL), SplitLine("400001", 300, _PARTIAL)),
        unfilled_qty=316,
    )


def test_unfilled_qty_is_rounded_up_in_the_requested_unit() -> None:
    """The buyer hears litres, so a part of a litre that no stock covers counts as one."""
    box = ContentPerSalesUnit(Decimal("2.5"), Unit.L)
    line = _line("400002", "Valio", stock=3, needed=5, codes=_PARTIAL)

    split = propose_split([line], {"400002": box}, query(quantity="12"), ())

    assert split is not None
    assert split.unfilled_qty == 5


def test_a_group_a_line_without_preference_gap_gives_none() -> None:
    """With a group A line, rank 1 covers the request, so there is nothing to split."""
    assert _split(_valio(), brands=()) is None


def test_no_stock_count_gives_none() -> None:
    """Unconfirmed stock cannot be split: the gateway cannot say how much each product gives."""
    line = _line("400003", "Valio", codes=(ReasonCode.STOCK_UNCONFIRMED,))

    assert _split(line, brands=()) is None


def test_a_late_line_is_never_split() -> None:
    """A split uses stock the buyer can get on time."""
    late = _line("400004", "Valio", stock=300, codes=_PARTIAL + _LATE)

    assert _split(late, brands=()) is None


def test_all_split_lines_share_the_date_of_the_first_line() -> None:
    """One product is never split over two dates, and one split is one delivery."""
    tuesday = MONDAY + timedelta(days=1)
    first = _line("400005", "Valio", price="0.90", stock=300, codes=_PARTIAL)
    other_day = _line(
        "400006", "Valio", price="0.95", stock=300, codes=_PARTIAL, available_date=tuesday
    )

    split = _split(first, other_day, brands=(), deliver_by=None)

    assert split is not None
    assert [line.product_id for line in split.lines] == ["400005"]


def test_a_filler_on_another_date_is_not_used() -> None:
    """The partial line fixes the date. A group A line on another day cannot join it."""
    tuesday = MONDAY + timedelta(days=1)
    valio = replace(_valio(), available_date=tuesday)

    assert _split(valio, _arla()) is None


def test_substitute_lines_are_ignored() -> None:
    """Another rule adds substitute lines. This one must not pick them as a filler."""
    substitute = replace(_valio(), substitute_for=samples.offer().lines[0].substitute_for)

    split = _split(substitute, _arla())

    assert split is not None
    assert [line.product_id for line in split.lines] == [_ARLA_ID]
    assert split.unfilled_qty == 616


def test_no_quantity_gives_none() -> None:
    """One sales unit requested: nothing to split."""
    assert _split(_valio(), _arla(), quantity=None) is None
