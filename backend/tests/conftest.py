import os

import pytest

from app.adapters.memory.repositories import InMemoryAgentKeyRepository

# Tests never read the real key from .env. app.main builds the app at import time, so the
# value must be set before any test module imports it.
os.environ["AGENT_KEY"] = "test-agent-key-0123456789"


@pytest.fixture
def agent_keys() -> InMemoryAgentKeyRepository:
    """Pass it to create_app; the demo key is seeded here, so a test can change it."""
    return InMemoryAgentKeyRepository()
