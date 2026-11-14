from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol

from app.domain.offer import AvailabilitySnapshot, Price


class PriceSource(Protocol):
    """The Valio Aimo price and availability APIs.

    Both raise UpstreamUnavailableError after the retries. Never call them under a lock.
    """

    def prices(self, product_ids: Sequence[str], requested_date: date) -> Mapping[str, Price]: ...

    def availability(
        self,
        product_ids: Sequence[str],
        requested_date: date,
    ) -> AvailabilitySnapshot: ...
