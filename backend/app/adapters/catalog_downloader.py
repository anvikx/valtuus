"""Download fresh catalog files before importing them."""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import SecretStr

_LOG = logging.getLogger(__name__)
_TIMEOUT = 60
_ATTEMPTS = 3
_DOWNLOAD_ERRORS = (HTTPError, URLError, TimeoutError, OSError)
_PRODUCTS_FILE = "valio_products.json"


@dataclass(frozen=True)
class DownloadedCatalog:
    products: Path
    reliability: Path | None
    carbon: Path | None


class CatalogDownloader:
    def __init__(self, base_url: str, api_key: SecretStr, data_dir: Path) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._data_dir = data_dir

    def download(self) -> DownloadedCatalog:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        products = self._products()
        reliability = self._optional(
            "delivery-reliability/download", "valio_delivery_reliability.csv"
        )
        carbon = self._optional("carbon-footprint/download", "valio_carbon_foot_print.csv")
        return DownloadedCatalog(products, reliability, carbon)

    def _products(self) -> Path:
        # Startup downloads the catalog, so an upstream outage during a restart took the site
        # down although the last good file was still on disk. _download replaces the file only
        # after a full read, so the file on disk is always a complete earlier catalog.
        previous = self._data_dir / _PRODUCTS_FILE
        try:
            return self._download("products/download", _PRODUCTS_FILE)
        except _DOWNLOAD_ERRORS as exc:
            if not previous.is_file():
                raise
            _LOG.warning("Could not download products, using previous file: %s", type(exc).__name__)
            return previous

    def _optional(self, endpoint: str, filename: str) -> Path | None:
        try:
            return self._download(endpoint, filename)
        except _DOWNLOAD_ERRORS as exc:
            _LOG.warning("Could not download %s: %s", filename, type(exc).__name__)
            return None

    def _download(self, endpoint: str, filename: str) -> Path:
        request = Request(
            f"{self._base_url}/{endpoint}",
            # The upstream's Cloudflare policy rejects urllib's default user agent.
            headers={"X-API-Key": self._api_key.get_secret_value(), "User-Agent": "curl/8.7.1"},
        )
        destination = self._data_dir / filename
        for attempt in range(_ATTEMPTS):
            try:
                with (
                    urlopen(request, timeout=_TIMEOUT) as response,
                    tempfile.NamedTemporaryFile(dir=self._data_dir, delete=False) as temporary,
                ):
                    temp_path = Path(temporary.name)
                    try:
                        while chunk := response.read(1024 * 1024):
                            temporary.write(chunk)
                    except BaseException:
                        temp_path.unlink(missing_ok=True)
                        raise
                try:
                    temp_path.replace(destination)
                finally:
                    temp_path.unlink(missing_ok=True)
                return destination
            except HTTPError as exc:
                if (exc.code != 429 and exc.code < 500) or attempt == _ATTEMPTS - 1:
                    raise
            except TimeoutError as exc:
                if attempt == _ATTEMPTS - 1:
                    raise exc
            except URLError as exc:
                if not isinstance(exc.reason, TimeoutError) or attempt == _ATTEMPTS - 1:
                    raise
        raise RuntimeError("download attempts exhausted")
