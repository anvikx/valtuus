import base64
import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic_core import to_jsonable_python

from app.domain.signature import NotVerified, Verification, Verified, VerifyFailure

_ALGORITHM = "EdDSA"
# The decoder skips characters outside the alphabet, so a part with junk would still pass.
_B64URL_PART = re.compile(r"[A-Za-z0-9_-]*")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _compact_json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def _json_object(part: str) -> dict[str, object] | None:
    """A JWS part as a JSON object. None when it is not base64url JSON or not an object."""
    try:
        value = json.loads(_b64url_decode(part))
    # A caller with no key can send deeply nested JSON. It must give a reason, not a 500.
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None

    return value if isinstance(value, dict) else None


class NullSigner:
    """Used when SIGNING_PRIVATE_KEY is empty. Responses carry signature: null."""

    def sign(self, payload: Mapping[str, object]) -> str | None:
        return None

    def public_keys(self) -> Sequence[Mapping[str, str]]:
        return ()

    def verify(self, jws: str) -> Verification:
        return NotVerified(VerifyFailure.UNKNOWN_KEY)


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

    def verify(self, jws: str) -> Verification:
        parts = jws.split(".")
        if len(parts) != 3 or not all(_B64URL_PART.fullmatch(part) for part in parts):
            return NotVerified(VerifyFailure.MALFORMED)

        header, payload = _json_object(parts[0]), _json_object(parts[1])
        if header is None or payload is None:
            return NotVerified(VerifyFailure.MALFORMED)

        if header.get("kid") != self._kid or header.get("alg") != _ALGORITHM:
            return NotVerified(VerifyFailure.UNKNOWN_KEY)

        try:
            signature = _b64url_decode(parts[2])
            self._key.public_key().verify(signature, f"{parts[0]}.{parts[1]}".encode("ascii"))
        except (ValueError, InvalidSignature):
            return NotVerified(VerifyFailure.BAD_SIGNATURE)

        return Verified(kid=self._kid, payload=payload)
