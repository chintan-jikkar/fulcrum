from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Values come from the environment, or from backend/.env (git-ignored) for local secrets.
    model_config = SettingsConfigDict(
        extra="ignore", env_file=Path(__file__).resolve().parents[1] / ".env"
    )

    # Default matches docker-compose.yml's local-only database. Real deployments set DATABASE_URL.
    database_url: str = "postgresql+psycopg://fulcrum:fulcrum@localhost:5432/fulcrum"

    # Local development only (D-058): every request is this user, with no token. Never set
    # DEV_AUTH_SUB on a deployed API.
    dev_auth_sub: str | None = None

    # Brand logos (D-067). The secret key (sk_...) stays on the server; without it the web
    # shows brand-colour tiles. Stored logos go in logo_dir, which is never committed.
    logo_dev_secret_key: str | None = None
    logo_dir: Path = Path(__file__).resolve().parents[1] / ".logos"


settings = Settings()
