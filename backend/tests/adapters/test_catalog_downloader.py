from datetime import datetime, timedelta
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from pydantic import SecretStr

from app.adapters.catalog_downloader import CatalogDownloader
from app.adapters.valio_client import ValioClient
from app.adapters.valio_requests import ValioRequests
from app.domain.constants import GATEWAY_TIMEZONE
from app.domain.errors import UpstreamRateLimitedError

downloader_download = CatalogDownloader.download


class _Clock:
    def __init__(self):
        self.at = datetime(2026, 11, 14, tzinfo=GATEWAY_TIMEZONE)
        self.slept = []

    def now(self):
        return self.at

    def advance(self, seconds):
        self.at += timedelta(seconds=seconds)

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.advance(seconds)


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr("app.adapters.valio_requests.sleep", clock.sleep)
    return clock


def _downloader(tmp_path, requests):
    return CatalogDownloader(
        "https://example.test/api/",
        SecretStr("secret"),
        tmp_path,
        requests,
    )


def test_download_retries_and_does_not_reuse_failed_enrichment(tmp_path, monkeypatch, clock):
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
    downloader = _downloader(tmp_path, ValioRequests(clock))

    result = downloader_download(downloader)

    assert calls.count("https://example.test/api/products/download") == 2
    assert result.products.read_bytes() == b"fresh"
    assert result.reliability is None
    assert result.carbon.read_bytes() == b"fresh"
    assert (tmp_path / "valio_delivery_reliability.csv").read_text() == "old"
    assert clock.slept == [0.5]


def _unreachable(request, timeout):
    raise URLError(ConnectionRefusedError("refused"))


def test_unreachable_upstream_falls_back_to_previous_products(tmp_path, monkeypatch, clock):
    """A restart during an upstream outage must not take the site down while a catalog exists."""
    destination = tmp_path / "valio_products.json"
    destination.write_text("old")
    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", _unreachable)
    downloader = _downloader(tmp_path, ValioRequests(clock))

    result = downloader_download(downloader)

    assert result.products == destination
    assert destination.read_text() == "old"


def test_unreachable_upstream_without_previous_products_fails(tmp_path, monkeypatch, clock):
    """With no catalog at all the gateway cannot quote, so startup must fail loudly."""
    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", _unreachable)
    downloader = _downloader(tmp_path, ValioRequests(clock))

    with pytest.raises(URLError):
        downloader_download(downloader)


@pytest.mark.parametrize("endpoint", ["products", "delivery-reliability", "carbon-footprint"])
def test_a_download_429_pauses_every_endpoint_without_retry(tmp_path, monkeypatch, clock, endpoint):
    """A 429 on an optional file must also stop the remaining downloads and offer calls."""
    calls = []
    destination = tmp_path / "valio_products.json"
    destination.write_bytes(b"old")

    def open_fake(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith(f"/{endpoint}/download"):
            raise HTTPError(request.full_url, 429, "paused", {}, None)
        return BytesIO(b"fresh")

    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", open_fake)
    monkeypatch.setattr("app.adapters.valio_client.urlopen", open_fake)
    requests = ValioRequests(clock)
    downloader = _downloader(tmp_path, requests)
    client = ValioClient("https://example.test/api/", SecretStr("secret"), requests)

    result = downloader_download(downloader)
    first_calls = list(calls)
    clock.advance(10.1)
    downloader_download(downloader)
    with pytest.raises(UpstreamRateLimitedError) as paused:
        client.prices(["1"], clock.now().date())

    endpoints = ["products", "delivery-reliability", "carbon-footprint"]
    assert len(first_calls) == endpoints.index(endpoint) + 1
    assert calls == first_calls
    assert paused.value.retry_after == 20
    assert paused.value.next_step == "Try again in 20 seconds."
    assert clock.slept == []
    assert result.products.read_bytes() == (b"old" if endpoint == "products" else b"fresh")
    clock.advance(19.9)
    monkeypatch.setattr(
        "app.adapters.catalog_downloader.urlopen",
        lambda *args, **kwargs: BytesIO(b"ok"),
    )

    assert downloader_download(downloader).products.read_bytes() == b"ok"


def test_a_429_without_a_previous_catalog_fails_without_retry(tmp_path, monkeypatch, clock):
    calls = []

    def limited(request, timeout):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 429, "paused", {}, None)

    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", limited)
    downloader = _downloader(tmp_path, ValioRequests(clock))

    with pytest.raises(UpstreamRateLimitedError) as initial:
        downloader_download(downloader)
    clock.advance(1)
    with pytest.raises(UpstreamRateLimitedError) as paused:
        downloader_download(downloader)

    assert len(calls) == 1
    assert initial.value.retry_after == 30
    assert paused.value.retry_after == 29
    assert clock.slept == []


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("https://example.test", 503, "down", {}, None),
        TimeoutError(),
        URLError(TimeoutError()),
    ],
)
def test_download_failures_are_retried_only_once(tmp_path, monkeypatch, clock, failure):
    calls = []

    def failing(request, timeout):
        calls.append(request.full_url)
        raise failure

    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", failing)
    downloader = _downloader(tmp_path, ValioRequests(clock))

    with pytest.raises(type(failure)):
        downloader_download(downloader)

    assert len(calls) == 2
    assert clock.slept == [0.5]
    assert list(tmp_path.iterdir()) == []


def test_a_timeout_during_download_keeps_the_previous_file_and_removes_partial_data(
    tmp_path, monkeypatch, clock
):
    destination = tmp_path / "valio_products.json"
    destination.write_bytes(b"old")
    calls = []

    class PartialResponse(BytesIO):
        def read(self, size):
            if self.tell():
                raise TimeoutError()
            return super().read(size)

    def open_fake(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith("/products/download"):
            return PartialResponse(b"incomplete")
        raise HTTPError(request.full_url, 404, "missing", {}, None)

    monkeypatch.setattr("app.adapters.catalog_downloader.urlopen", open_fake)

    result = downloader_download(_downloader(tmp_path, ValioRequests(clock)))

    assert result.products.read_bytes() == b"old"
    assert calls.count("https://example.test/api/products/download") == 2
    assert clock.slept == [0.5]
    assert list(tmp_path.iterdir()) == [destination]
