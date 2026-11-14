from io import BytesIO
from urllib.error import HTTPError

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


def test_required_failure_preserves_previous_file(tmp_path, monkeypatch):
    destination = tmp_path / "valio_products.json"
    destination.write_text("old")

    def fail(request, timeout):
        raise HTTPError(request.full_url, 403, "forbidden", {}, None)

    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", fail)
    downloader = CatalogDownloader("https://example.test/api", SecretStr("secret"), tmp_path)

    with pytest.raises(HTTPError):
        downloader_download(downloader)

    assert destination.read_text() == "old"
