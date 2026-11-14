from collections.abc import Mapping, Sequence
from typing import Protocol


class Signer(Protocol):
    def sign(self, payload: Mapping[str, object]) -> str | None:
        """Compact JWS over the response body without its signature field. None = not signed."""
        ...

    def public_keys(self) -> Sequence[Mapping[str, str]]:
        """JWKs that check the signatures, served at /.well-known/jwks.json."""
        ...
