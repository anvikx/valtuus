from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Aware time in the gateway time zone."""
        ...
