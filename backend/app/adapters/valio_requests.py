"""Shared caller cooldown and retry rules for every Valio endpoint."""

import logging
import math
from collections.abc import Callable
from datetime import datetime, timedelta
from http import HTTPStatus
from time import sleep
from urllib.error import HTTPError, URLError

from app.domain.constants import VALIO_COOLDOWN_SECONDS
from app.domain.errors import UpstreamRateLimitedError
from app.services.ports.clock import Clock

_LOG = logging.getLogger(__name__)
_MAX_ATTEMPTS = 3
_FIRST_RETRY_WAIT_SECONDS = 0.5


class ValioRequests:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._paused_until: datetime | None = None

    def send[T](self, operation: Callable[[], T]) -> T:
        """Retries a 5xx or a timeout with a doubling wait. A 429 pauses all endpoints."""
        wait = _FIRST_RETRY_WAIT_SECONDS
        for _ in range(_MAX_ATTEMPTS - 1):
            self._check_pause()
            try:
                return self._attempt(operation)
            except (URLError, TimeoutError) as exc:
                if not _is_transient(exc):
                    raise

            sleep(wait)
            wait *= 2

        self._check_pause()
        return self._attempt(operation)

    def _check_pause(self) -> None:
        if self._paused_until is None:
            return

        remaining = math.ceil((self._paused_until - self._clock.now()).total_seconds())
        if remaining > 0:
            raise UpstreamRateLimitedError(remaining)

    def _attempt[T](self, operation: Callable[[], T]) -> T:
        try:
            return operation()
        except HTTPError as exc:
            if exc.code != HTTPStatus.TOO_MANY_REQUESTS:
                raise

            self._paused_until = self._clock.now() + timedelta(seconds=VALIO_COOLDOWN_SECONDS)
            _LOG.warning("Valio answered 429. Pausing all calls.")
            raise UpstreamRateLimitedError(VALIO_COOLDOWN_SECONDS) from exc


def _is_transient(exc: URLError | TimeoutError) -> bool:
    # HTTPError is a URLError, so it goes first. A refused connection is not transient.
    if isinstance(exc, HTTPError):
        return exc.code >= HTTPStatus.INTERNAL_SERVER_ERROR
    if isinstance(exc, URLError):
        return isinstance(exc.reason, TimeoutError)
    return True
