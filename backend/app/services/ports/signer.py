from collections.abc import Mapping, Sequence
from typing import Protocol

from app.domain.signature import Verification


class Signer(Protocol):
    def sign(self, payload: Mapping[str, object]) -> str | None:
        """Compact JWS over the response body without its signature field. None = not signed."""
        ...

    def public_keys(self) -> Sequence[Mapping[str, str]]:
        """JWKs that check the signatures, served at /.well-known/jwks.json."""
        ...

    def verify(self, jws: str) -> Verification:
        """Checks a compact JWS against the published keys and returns its payload."""
        ...
