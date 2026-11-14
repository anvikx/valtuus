import pytest

from app.api.results import cart_response
from app.domain.enums import CartState
from tests.adapters import samples

_PUBLIC_URL = "https://junction.anvik.fi"


def test_pending_cart_links_to_approval_page():
    response = cart_response(samples.cart(state=CartState.PENDING_APPROVAL), _PUBLIC_URL)

    assert response.approve_url == f"{_PUBLIC_URL}/carts/c_1"


@pytest.mark.parametrize(
    "state", [state for state in CartState if state is not CartState.PENDING_APPROVAL]
)
def test_cart_without_decision_has_no_link(state):
    """An agent shows the link to the main user, so a cart with nothing to approve has none."""
    response = cart_response(samples.cart(state=state), _PUBLIC_URL)

    assert response.approve_url is None
