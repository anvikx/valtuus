from pathlib import Path

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
    valio_base_url: str = "https://junction26.valioaimo.fi/api"
    # SecretStr keeps the key out of reprs and logs.
    valio_api_key: SecretStr = SecretStr("")
    # Bearer key of the demo buyer agent. Only its hash is kept after startup.
    agent_key: SecretStr = SecretStr("")
    # The main user logs in with it to approve carts and change the mandate.
    main_user_password: SecretStr = SecretStr("")
    # The approve_url in a cart points here, so the main user opens the right page.
    public_url: str = "https://junction.anvik.fi"
    # The challenge product file. Gitignored: the data stays inside the challenge.
    data_dir: Path = Path("data")
    # postgresql+psycopg://... Empty means the in-memory store, which loses all data on
    # restart; Compose refuses to start without it. Secret: the URL holds the password.
    database_url: SecretStr = SecretStr("")
