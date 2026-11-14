from collections.abc import Mapping


class NullSigner:
    """Used until SIGNING_PRIVATE_KEY is wired. Responses carry signature: null."""

    def sign(self, payload: Mapping[str, object]) -> str | None:
        return None
