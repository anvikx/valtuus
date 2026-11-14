from datetime import UTC, datetime

import pytest

from app.adapters.clock import FixedClock, SystemClock
from app.domain.constants import GATEWAY_TIMEZONE


def test_fixed_clock_reports_gateway_time():
    """The agent resolves "Monday" from this time, so it must be Helsinki time."""
    clock = FixedClock(datetime(2026, 11, 14, 8, 0, tzinfo=UTC))

    now = clock.now()

    assert now.tzinfo == GATEWAY_TIMEZONE
    assert now.hour == 10


def test_fixed_clock_refuses_naive_time():
    """A naive DEMO_NOW would move every deadline by the server's zone."""
    with pytest.raises(ValueError, match="zone"):
        FixedClock(datetime(2026, 11, 14, 10, 0))


def test_system_clock_is_aware():
    """Deadline checks compare aware times. A naive time would raise at the first compare."""
    now = SystemClock().now()

    assert now.tzinfo == GATEWAY_TIMEZONE
