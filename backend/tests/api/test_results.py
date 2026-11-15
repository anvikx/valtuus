import pytest

from app.api.results import cart_response
from app.domain.enums import CartState
from tests.adapters import samples

_PUBLIC_URL = "https://junction.anvik.fi"


def test_pending_cart_links_to_approval_page():
    response = cart_response(samples.cart(state=CartState.PENDING_APPROVAL), _PUBLIC_URL)

    assert response.approve_url == f"{_PUBLIC_URL}/carts/c_1"


def test_pending_cart_tells_agent_to_show_link():
    """Agents forget the link unless the result tells them, so the main user never sees the cart."""
    cart = samples.cart(state=CartState.PENDING_APPROVAL)

    response = cart_response(cart, _PUBLIC_URL)

    assert response.next_step is not None
    assert f"{_PUBLIC_URL}/carts/c_1" in response.next_step
    assert cart.approve_before.isoformat() in response.next_step


@pytest.mark.parametrize(
    "state", [state for state in CartState if state is not CartState.PENDING_APPROVAL]
)
def test_cart_without_decision_has_no_link(state):
    """An agent shows the link to the main user, so a cart with nothing to approve has none."""
    response = cart_response(samples.cart(state=state), _PUBLIC_URL)

    assert response.approve_url is None
    assert response.next_step is None


def test_cart_details_serializes_changes_and_preserves_money():
    from app.api.results import cart_details_response
    from app.domain.cart import LineChange
    from app.services.cart_service import CartDetails

    details = CartDetails(
        cart=samples.cart(),
        revision_count=2,
        changes=(
            LineChange("changed", "Changed", 20, 40),
            LineChange("added", "Added", None, 10),
            LineChange("removed", "Removed", 5, None),
        ),
    )

    body = cart_details_response(details, _PUBLIC_URL).model_dump(mode="json")

    assert body["revision"] == details.cart.revision
    assert body["revision_count"] == 2
    assert body["total_ex_vat"] == "1010.00"
    assert body["changes"] == [
        {"product_id": "changed", "name": "Changed", "qty_before": 20, "qty_after": 40},
        {"product_id": "added", "name": "Added", "qty_before": None, "qty_after": 10},
        {"product_id": "removed", "name": "Removed", "qty_before": 5, "qty_after": None},
    ]
    assert body["approve_url"] == f"{_PUBLIC_URL}/carts/c_1"
