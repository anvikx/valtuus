from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from pydantic import SecretStr

from app.adapters.catalog_downloader import CatalogDownloader

downloader_download = CatalogDownloader.download


def test_download_retries_and_does_not_reuse_failed_enrichment(tmp_path, monkeypatch):
    calls = []
    (tmp_path / "valio_products.json").write_text("old")
    (tmp_path / "valio_delivery_reliability.csv").write_text("old")

    def open_fake(request, timeout):
        calls.append(request.full_url)
        assert request.get_header("X-api-key") == "secret"
        assert request.get_header("User-agent") == "curl/8.7.1"
        assert timeout == 60
        if "delivery-reliability" in request.full_url:
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        if "products" in request.full_url and calls.count(request.full_url) == 1:
            raise HTTPError(request.full_url, 503, "retry", {}, None)
        return BytesIO(b"fresh")

    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", open_fake)
    downloader = CatalogDownloader("https://example.test/api/", SecretStr("secret"), tmp_path)

    result = downloader_download(downloader)

    assert calls.count("https://example.test/api/products/download") == 2
    assert result.products.read_bytes() == b"fresh"
    assert result.reliability is None
    assert result.carbon.read_bytes() == b"fresh"
    assert (tmp_path / "valio_delivery_reliability.csv").read_text() == "old"


def _unreachable(request, timeout):
    raise URLError(ConnectionRefusedError("refused"))


def test_unreachable_upstream_falls_back_to_previous_products(tmp_path, monkeypatch):
    """A restart during an upstream outage must not take the site down while a catalog exists."""
    destination = tmp_path / "valio_products.json"
    destination.write_text("old")
    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", _unreachable)
    downloader = CatalogDownloader("https://example.test/api", SecretStr("secret"), tmp_path)

    result = downloader_download(downloader)

    assert result.products == destination
    assert destination.read_text() == "old"


def test_unreachable_upstream_without_previous_products_fails(tmp_path, monkeypatch):
    """With no catalog at all the gateway cannot quote, so startup must fail loudly."""
    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", _unreachable)
    downloader = CatalogDownloader("https://example.test/api", SecretStr("secret"), tmp_path)

    with pytest.raises(URLError):
        downloader_download(downloader)
