import base64
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app

_JWKS_PATH = "/.well-known/jwks.json"
# Any 32 bytes are an Ed25519 seed.
_SEED = base64.b64encode(bytes(range(32))).decode()


def _jwks(signing_private_key: str) -> dict[str, object]:
    settings = Settings(signing_private_key=SecretStr(signing_private_key))
    with TestClient(create_app(settings)) as client:
        response = client.get(_JWKS_PATH)

    assert response.status_code == HTTPStatus.OK
    return response.json()


def test_jwks_serves_the_signing_key():
    """Agents fetch this key to check offers and orders. A missing key makes signatures useless."""
    jwks = _jwks(_SEED)

    (key,) = jwks["keys"]
    assert key["kty"] == "OKP"
    assert key["crv"] == "Ed25519"
    assert key["alg"] == "EdDSA"
    assert key["kid"]


def test_jwks_is_empty_without_a_signing_key():
    """Responses go out with signature null then, and no key may suggest otherwise."""
    assert _jwks("") == {"keys": []}


@pytest.mark.parametrize("bad_key", ["not base64!", base64.b64encode(bytes(31)).decode()])
def test_app_refuses_a_bad_signing_key(bad_key: str):
    """A cut or mistyped key must stop the deploy, not sign with a key nobody can check."""
    settings = Settings(signing_private_key=SecretStr(bad_key))

    with pytest.raises(ValueError):
        create_app(settings)
