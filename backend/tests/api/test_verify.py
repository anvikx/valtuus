import base64
import json
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.adapters.signer import Ed25519Signer
from app.config import Settings
from app.main import create_app

_VERIFY_PATH = "/api/v1/verify"
_SEED = bytes(range(32))
_BODY = {
    "order_id": "o_1",
    "total_ex_vat": "1010.00",
}


def _verify(request: dict[str, object]) -> dict[str, object]:
    settings = Settings(signing_private_key=SecretStr(base64.b64encode(_SEED).decode()))
    with TestClient(create_app(settings)) as client:
        response = client.post(_VERIFY_PATH, json=request)

    assert response.status_code == HTTPStatus.OK
    return response.json()


def _token() -> str:
    return Ed25519Signer(_SEED).sign(_BODY)


def test_signed_body_verifies_without_a_key():
    """Anyone may check a statement: the verify call needs no agent key and no session."""
    result = _verify({"jws": _token(), "body": {**_BODY, "signature": _token()}})

    assert result["valid"] is True
    assert result["kid"]
    assert result["payload"] == _BODY
    assert result["body_matches"] is True


def test_changed_visible_price_keeps_the_jws_valid_but_does_not_match():
    """Tamper case 2: the signature still holds, so only body_matches can stop the trust mark."""
    result = _verify({"jws": _token(), "body": {**_BODY, "total_ex_vat": "1.00"}})

    assert result["valid"] is True
    assert result["body_matches"] is False


def test_no_body_leaves_body_matches_empty():
    """Without a body nothing was compared, so the answer is null, not true."""
    result = _verify({"jws": _token()})

    assert result["valid"] is True
    assert result["body_matches"] is None


def test_changed_payload_is_not_valid():
    """Tamper case 1: one changed payload byte makes the statement not valid."""
    header, _payload, signature = _token().split(".")
    changed = base64.urlsafe_b64encode(json.dumps({**_BODY, "total_ex_vat": "1.00"}).encode())
    token = f"{header}.{changed.rstrip(b'=').decode()}.{signature}"

    result = _verify({"jws": token, "body": _BODY})

    assert result == {
        "valid": False,
        "kid": None,
        "payload": None,
        "body_matches": None,
        "reason": "BAD_SIGNATURE",
    }


@pytest.mark.parametrize("depth", [995, 50_000], ids=["parses", "too-deep-to-parse"])
def test_deeply_nested_body_gives_no_server_error(depth: int):
    """The route has no auth. A hostile body must get a client error or an answer, not a 500."""
    deep = '{"a":' * depth + "1" + "}" * depth
    raw = f'{{"jws":"{_token()}","body":{deep}}}'
    settings = Settings(signing_private_key=SecretStr(base64.b64encode(_SEED).decode()))

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.post(
            _VERIFY_PATH,
            content=raw,
            headers={"content-type": "application/json"},
        )

    assert response.status_code < HTTPStatus.INTERNAL_SERVER_ERROR
