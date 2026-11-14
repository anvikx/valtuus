import base64
import json
from dataclasses import asdict

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.adapters.signer import Ed25519Signer, NullSigner
from app.api.results import order_response
from tests.adapters import samples

# RFC 8037 appendix A.1 key and the A.3 thumbprint of its public key.
_RFC_SEED = "nWGxne_9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A"
_RFC_X = "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"
_RFC_THUMBPRINT = "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signer() -> Ed25519Signer:
    return Ed25519Signer(_b64url_decode(_RFC_SEED))


def _order_body() -> dict[str, object]:
    body = asdict(samples.order())
    del body["signature"]
    return body


def test_published_key_is_the_rfc_8037_key_with_its_thumbprint_as_id():
    """An agent picks the key by kid. A wrong thumbprint or x makes every check fail."""
    (key,) = _signer().public_keys()

    assert key == {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": _RFC_X,
        "kid": _RFC_THUMBPRINT,
        "alg": "EdDSA",
        "use": "sig",
    }


def test_signature_verifies_with_the_published_key():
    """An agent checks header.payload against the JWKS key. Other signed bytes fail the check."""
    signer = _signer()
    (key,) = signer.public_keys()

    token = signer.sign(_order_body())

    header, payload, signature = token.split(".")
    public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(key["x"]))
    public_key.verify(_b64url_decode(signature), f"{header}.{payload}".encode("ascii"))
    assert json.loads(_b64url_decode(header)) == {
        "alg": "EdDSA",
        "kid": _RFC_THUMBPRINT,
    }


def test_signed_payload_equals_the_response_body():
    """The agent compares the signed payload with the body it got. Money must stay "12.50"."""
    order = samples.order()
    expected = order_response(order).model_dump(mode="json")
    del expected["signature"]

    token = _signer().sign(_order_body())

    payload = json.loads(_b64url_decode(token.split(".")[1]))
    assert payload == expected


def test_seed_of_wrong_length_is_refused():
    """A cut key in .env must stop the startup, not sign with a key nobody can check."""
    with pytest.raises(ValueError, match="32 bytes"):
        Ed25519Signer(bytes(31))


def test_null_signer_publishes_no_key():
    """With no signing key the JWKS stays empty, so no agent trusts a key that signs nothing."""
    signer = NullSigner()

    assert signer.sign(_order_body()) is None
    assert signer.public_keys() == ()
