import base64
import hashlib
import json
from collections.abc import Mapping, Sequence

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic_core import to_jsonable_python

_ALGORITHM = "EdDSA"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _compact_json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


class NullSigner:
    """Used when SIGNING_PRIVATE_KEY is empty. Responses carry signature: null."""

    def sign(self, payload: Mapping[str, object]) -> str | None:
        return None

    def public_keys(self) -> Sequence[Mapping[str, str]]:
        return ()


class Ed25519Signer:
    """Compact JWS with EdDSA (RFC 7515, RFC 8037). The kid is the RFC 7638 thumbprint."""

    def __init__(self, seed: bytes) -> None:
        self._key = Ed25519PrivateKey.from_private_bytes(seed)
        public = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        # RFC 7638 hashes only the required members, in this lexical order.
        jwk = {
            "crv": "Ed25519",
            "kty": "OKP",
            "x": _b64url(public),
        }
        self._kid = _b64url(hashlib.sha256(_compact_json(jwk)).digest())
        self._jwk = {
            **jwk,
            "kid": self._kid,
            "alg": _ALGORITHM,
            "use": "sig",
        }

    def sign(self, payload: Mapping[str, object]) -> str:
        # pydantic's JSON mode, so Decimal and datetime read as in the response body.
        header = _b64url(_compact_json({"alg": _ALGORITHM, "kid": self._kid}))
        body = _b64url(_compact_json(to_jsonable_python(payload)))
        signing_input = f"{header}.{body}"
        signature = self._key.sign(signing_input.encode("ascii"))
        return f"{signing_input}.{_b64url(signature)}"

    def public_keys(self) -> Sequence[Mapping[str, str]]:
        return (self._jwk,)
