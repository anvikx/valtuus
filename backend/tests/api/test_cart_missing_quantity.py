import pytest

from app.api.schemas.carts import CartRequest
from app.domain.enums import ErrorCode, ReasonCode
from app.domain.errors import NeedsClarificationError


@pytest.mark.parametrize("quantity", [{}, {"qty": None}], ids=["omitted", "null"])
def test_cart_requires_buyer_quantity(quantity):
    """A vague request must ask the buyer rather than default to one sales unit."""
    request = CartRequest.model_validate(
        {
            "lines": [{"offer_id": "o_milk", "product_id": "milk", **quantity}],
            "request_text": "buy me milk",
        }
    )

    with pytest.raises(NeedsClarificationError) as caught:
        request.to_domain()

    error = caught.value
    assert error.code is ErrorCode.VALIDATION_ERROR
    assert error.reason_code is ReasonCode.NEEDS_CLARIFICATION
    assert error.missing == ("lines[0].qty",)
    assert "How many sales units of milk?" in error.message
    assert error.next_step == "Ask the buyer, then send the call again with the missing fields."
