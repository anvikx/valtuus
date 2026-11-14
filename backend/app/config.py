from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Root .env for `make dev-be` (cwd is backend/). Missing files are skipped, and in
    # Docker the values come from Compose env_file instead.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        extra="ignore",
    )

    app_name: str = "junction-2026"
