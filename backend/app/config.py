from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Default matches docker-compose.yml's local-only database. Real deployments set DATABASE_URL.
    database_url: str = "postgresql+psycopg://fulcrum:fulcrum@localhost:5432/fulcrum"


settings = Settings()
