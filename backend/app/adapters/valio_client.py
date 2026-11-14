from collections.abc import Mapping, Sequence
from datetime import date

from pydantic import SecretStr

from app.domain.offer import AvailabilitySnapshot, Price


class ValioClient:
    """The Valio Aimo price and availability APIs. Raises UpstreamUnavailableError."""

    def __init__(self, base_url: str, api_key: SecretStr) -> None:
        self._base_url = base_url
        self._api_key = api_key

    def prices(self, product_ids: Sequence[str], requested_date: date) -> Mapping[str, Price]:
        raise NotImplementedError("ValioClient.prices")

    def availability(
        self,
        product_ids: Sequence[str],
        requested_date: date,
    ) -> AvailabilitySnapshot:
        raise NotImplementedError("ValioClient.availability")
