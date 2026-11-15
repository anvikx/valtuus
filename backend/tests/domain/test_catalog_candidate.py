from decimal import Decimal

import pytest

from app.domain.catalog import ContentPerSalesUnit, SearchQuery
from app.domain.catalog_candidate import candidate
from app.domain.catalog_search import NameMatch
from app.domain.enums import Unit
from tests.fakes.offer_data import product


@pytest.mark.parametrize(
    ("pack_size", "quantity", "boxes", "delivered", "excess"),
    [
        pytest.param("5", "1000", 200, "1000", "0", id="1000-l-five-litre-boxes"),
        pytest.param("5", "12", 3, "15", "3", id="12-l-five-litre-boxes"),
        pytest.param("20", "1000", 50, "1000", "0", id="1000-l-two-times-10-l-boxes"),
        pytest.param("20", "41", 3, "60", "19", id="41-l-two-times-10-l-boxes"),
    ],
)
def test_search_shows_box_surplus(pack_size, quantity, boxes, delivered, excess):
    """The buyer sees both the full box count and how much more than requested it delivers."""
    boxed = product(content=ContentPerSalesUnit(Decimal(pack_size), Unit.L))
    query = SearchQuery(
        query="milk",
        required_attributes=(),
        quantity=Decimal(quantity),
        unit=Unit.L,
        deliver_by=None,
        preferred_brands=(),
    )

    found = candidate(boxed, NameMatch(inside_word=False, words=1), query)

    assert found.sales_units_needed == boxes
    assert found.quantity_delivered == Decimal(delivered)
    assert found.quantity_over_request == Decimal(excess)
