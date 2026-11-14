from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Root .env for `make dev-be` (cwd is backend/). Missing files are skipped, and in
    # Docker the values come from Compose env_file instead.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        extra="ignore",
    )

    app_name: str = "junction-2026"
    valio_base_url: str = "https://junction26.valioaimo.fi"
    # SecretStr keeps the key out of reprs and logs.
    valio_api_key: SecretStr = SecretStr("")
    # Bearer key of the demo buyer agent. Only its hash is kept after startup.
    agent_key: SecretStr = SecretStr("")
