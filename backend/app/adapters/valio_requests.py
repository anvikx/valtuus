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
_RETRY_WAIT_SECONDS = 0.5


class ValioRequests:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._paused_until: datetime | None = None

    def send[T](self, operation: Callable[[], T]) -> T:
        """One retry on 5xx/timeouts. A 429 pauses all endpoints without a retry."""
        self._check_pause()
        try:
            return self._attempt(operation)
        except HTTPError as exc:
            if exc.code < HTTPStatus.INTERNAL_SERVER_ERROR:
                raise
        except URLError as exc:
            if not isinstance(exc.reason, TimeoutError):
                raise
        except TimeoutError:
            pass

        sleep(_RETRY_WAIT_SECONDS)
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
