"""Application configuration loaded from environment variables (Section 8.4)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Environment
    environment: str = "development"
    frontend_url: str = "http://localhost:5173"

    # Database
    database_url: str = "postgresql+psycopg://yapi:yapi_dev_password@localhost:5432/yapi"

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_anon_key: str = ""

    # Auth
    jwt_secret: str = "dev-insecure-secret-change-me"  # legacy HS256 shared secret
    jwt_algorithm: str = "HS256"
    # Optional override for the public JWKS endpoint used to verify asymmetric
    # (ES256/RS256) access tokens under Supabase's new signing keys. When blank
    # it is derived from supabase_url: {SUPABASE_URL}/auth/v1/.well-known/jwks.json
    supabase_jwks_url: str = ""
    # JWT access token lifetime 1h, refresh 8h inactivity (Section 8.1)
    access_token_ttl_seconds: int = 3600
    inactivity_timeout_seconds: int = 8 * 3600

    # AI
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Email
    resend_api_key: str = ""
    email_from: str = "Yapı <bildirim@yapi.app>"

    # Security
    rate_limit_per_ip_per_minute: int = 100
    rate_limit_per_user_per_minute: int = 1000

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        origins = {self.frontend_url}
        if not self.is_production:
            origins.update({"http://localhost:5173", "http://127.0.0.1:5173"})
        return [o for o in origins if o]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
