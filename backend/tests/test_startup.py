import pytest
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app


def test_app_refuses_to_start_without_agent_key() -> None:
    """With no key the agent door would have no working credential, so the deploy must fail."""
    settings = Settings(agent_key=SecretStr(""))

    with pytest.raises(ValueError, match="empty"):
        create_app(settings)
