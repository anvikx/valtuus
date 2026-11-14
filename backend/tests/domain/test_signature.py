import pytest

from app.domain.signature import body_matches

_PAYLOAD = {
    "order_id": "o_1",
    "total_ex_vat": "1010.00",
    "count": 1,
    "lines": [{"qty": 2}],
}


def _without(key: str) -> dict[str, object]:
    return {name: value for name, value in _PAYLOAD.items() if name != key}


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(dict(_PAYLOAD), True, id="same"),
        pytest.param({**_PAYLOAD, "signature": "h.p.s"}, True, id="with-its-signature"),
        pytest.param({**_PAYLOAD, "total_ex_vat": "1.00"}, False, id="price-changed"),
        pytest.param(_without("total_ex_vat"), False, id="field-missing"),
        pytest.param({**_PAYLOAD, "extra": "x"}, False, id="field-added"),
        pytest.param({**_PAYLOAD, "count": True}, False, id="number-to-boolean"),
        pytest.param({**_PAYLOAD, "count": 1.0}, False, id="int-to-float"),
        pytest.param({**_PAYLOAD, "lines": [{"qty": 3}]}, False, id="nested-changed"),
    ],
)
def test_body_matches_only_the_signed_payload(body: dict[str, object], *, expected: bool):
    """Tamper case 2: a valid JWS next to a changed visible value must not show the trust mark."""
    assert body_matches(_PAYLOAD, body) is expected
