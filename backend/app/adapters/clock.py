from datetime import datetime

from app.domain.constants import GATEWAY_TIMEZONE


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(GATEWAY_TIMEZONE)


class FixedClock:
    """Holds one moment. DEMO_NOW uses it to run the demo before the mock's order deadline."""

    def __init__(self, at: datetime) -> None:
        # A naive time has no zone, so "before the deadline" would depend on the server.
        if at.tzinfo is None:
            raise ValueError("FixedClock needs a time with a zone")

        self._at = at.astimezone(GATEWAY_TIMEZONE)

    def now(self) -> datetime:
        return self._at
