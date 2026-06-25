"""Application configuration loaded from environment variables (Section 8.4)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Environment
    environment: str = "development"
    frontend_url: str = "http://localhost:5173"

    # Observability (error monitoring). When SENTRY_DSN is blank, Sentry is fully
    # disabled — nothing is initialized and no data leaves the process.
    sentry_dsn: str = ""

    # Database
    database_url: str = "postgresql+psycopg://yapi:yapi_dev_password@localhost:5432/yapi"
    # CR-040: dedicated escalated/owner connection for the paths that must BYPASS
    # row-level security — Alembic migrations (ALTER/CREATE POLICY), the auth user
    # lookup (reads users before company_id is known), the cron scheduler (all
    # companies), and the login-stamp write. When BLANK, everything falls back to
    # database_url, so single-URL deploys and the SQLite test suite are unchanged.
    # Rollout: set database_url = yapi_app (NOBYPASSRLS) and admin_database_url =
    # the service_role/owner URL. Rollback: point database_url back at service_role.
    admin_database_url: str = ""

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
    # Verbose auth diagnostics. Defaults on outside production; set DEBUG_AUTH=0 to silence.
    debug_auth: bool = True
    # JWT access token lifetime 1h, refresh 8h inactivity (Section 8.1)
    access_token_ttl_seconds: int = 3600
    inactivity_timeout_seconds: int = 8 * 3600

    # AI
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    # Email (CR-006-B: Resend)
    resend_api_key: str = ""
    email_from: str = "Yapı <bildirim@yapi.app>"
    # Resend free-tier test sender; override once a verified domain is added.
    resend_from_email: str = "onboarding@resend.dev"
    resend_from_name: str = "Yapı Bildirimleri"
    # CR-012: outbound email is unreliable from the Resend test sender. Set
    # EMAIL_VERIFIED_DOMAIN=1 only once a verified domain is configured; until then
    # the recurring-digest automation delivers in-app only and never tries email.
    email_verified_domain: bool = False

    # CR-012: shared secret gating the internal scheduler endpoint
    # (POST /internal/automations/run-due). NEVER committed — set as a Railway env
    # var. Blank => the endpoint rejects every request (no accidental open cron).
    internal_cron_secret: str = ""

    # Security
    rate_limit_per_ip_per_minute: int = 100
    rate_limit_per_user_per_minute: int = 1000
    # CR-002-I targeted limits
    login_max_attempts: int = 5
    login_lockout_seconds: int = 15 * 60
    import_rate_per_minute: int = 10
    ai_import_rate_per_minute: int = 5
    # CR-007-E: AI agent safety budget. Ceilings raised so extended thinking
    # (when enabled) + the answer both fit within one response.
    ai_agent_rate_per_minute: int = 10
    ai_agent_max_tokens: int = 5000
    ai_agent_timeout_seconds: int = 90
    # Extended thinking for the agent loop. OFF by default; flipped on per-env
    # (Railway) after deploy. The budget must stay below ai_agent_max_tokens so
    # the answer still fits. Thinking is never enabled on the forced-final
    # iteration (the API rejects thinking + a forced tool_choice).
    ai_agent_thinking_enabled: bool = False
    ai_agent_thinking_budget: int = 1536
    # CR-008-I: write-endpoint limits (workspace pin/reorder, vendor merge/link).
    workspace_write_rate_per_minute: int = 120
    vendor_write_rate_per_minute: int = 30
    # CR-014: when true, the FX service may lazily fetch live TCMB rates over the
    # network (prod default). Tests disable this so no test hits the network — the
    # cache-based walk-back over seeded fx_rates still works with it off.
    fx_live_fetch: bool = True
    # Field encryption (Fernet passphrase). Optional; never exposed to frontend.
    encryption_key: str = ""
    # Require directors to have MFA (enforced via the token AAL claim).
    require_director_mfa: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        # Always allow the known dev ports, the deployed Vercel frontend, and the
        # FRONTEND_URL env var (so prod requests from Vercel are never CORS-blocked).
        origins = {
            "http://localhost:5173",
            "http://localhost:3000",
            "https://yapi-code.vercel.app",
            self.frontend_url,
        }
        if not self.is_production:
            origins.add("http://127.0.0.1:5173")
        return [o for o in origins if o]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
