import dataclasses

from app.domain.cart import LineChange, cart_changes
from tests.adapters import samples

_OAT = samples.cart().lines[0]
_MILK = dataclasses.replace(_OAT, product_id="p_1", name="Milk 1 l")


def test_changes_list_added_removed_and_new_quantities():
    """The main user must see what moved since the version they saw, line by line."""
    before = (_OAT, _MILK)
    after = (dataclasses.replace(_MILK, qty=5), dataclasses.replace(_OAT, product_id="p_3"))

    changes = cart_changes(before, after)

    assert changes == (
        LineChange("p_1", "Milk 1 l", qty_before=2, qty_after=5),
        LineChange("p_3", "Oat milk 1 l", qty_before=None, qty_after=2),
        LineChange("p_2", "Oat milk 1 l", qty_before=2, qty_after=None),
    )


def test_same_product_and_quantity_is_no_change():
    """A new price or offer for the same quantity is not a change the main user asked for."""
    moved = dataclasses.replace(_OAT, offer_id="of_9", unit_price=samples.LARGE_MONEY)

    assert cart_changes((_OAT,), (moved,)) == ()
