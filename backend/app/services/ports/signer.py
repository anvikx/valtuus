from collections.abc import Mapping
from typing import Protocol


class Signer(Protocol):
    def sign(self, payload: Mapping[str, object]) -> str | None:
        """Compact JWS over the response body without its signature field. None = not signed."""
        ...
