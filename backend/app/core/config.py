"""Application settings, loaded and validated once from the environment.

Every tunable lives here; nothing else in the codebase reads ``os.environ``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SlaPair = Annotated[tuple[int, int], NoDecode]

DEFAULT_JWT_SECRET = "change-me-32-bytes-minimum"  # noqa: S105 - sentinel, rejected in production


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),  # repo-root .env when run from backend/; local wins
        env_file_encoding="utf-8",
        extra="ignore",  # .env also carries settings for later phases and other services
        case_sensitive=False,
    )

    # ---- core
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Tasky"
    app_base_url: str = "http://localhost:5173"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/incidents"
    db_pool_size: int = Field(default=5, ge=1, le=50)
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_json: bool | None = None  # None -> JSON everywhere except development
    git_sha: str = "dev"

    # ---- auth
    jwt_secret: str = DEFAULT_JWT_SECRET
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    allow_self_register: bool = True
    # Demo deployments only: the login page offers one-click demo accounts (their password
    # is public). Real deployments leave this off: people sign up and create their teams.
    demo_mode: bool = False
    # None -> Secure cookie everywhere except development (plain http://localhost)
    cookie_secure: bool | None = None
    # Forgot-password links are single-use and expire after this many minutes.
    password_reset_minutes: int = Field(default=30, ge=5, le=1440)

    # ---- Google sign-in (OAuth 2.0 authorization code + PKCE). Off unless both are set.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Default: APP_BASE_URL + /api/v1/auth/google/callback. Must match the Google console.
    google_redirect_uri: str | None = None

    # ---- copy accounts into Supabase Auth (Authentication -> Users). Off unless both are
    # set. Copies only: this app keeps doing its own sign-in; no passwords are sent.
    supabase_url: str | None = None  # https://<project-ref>.supabase.co
    supabase_service_role_key: str | None = None
    supabase_auth_sync_seconds: int = Field(default=60, ge=10, le=3600)

    # ---- rate limits (requests per minute; in-memory, per process)
    rate_limit_enabled: bool = True
    login_rate_limit_per_min: int = Field(default=5, ge=1)
    register_rate_limit_per_min: int = Field(default=3, ge=1)
    forgot_password_rate_limit_per_min: int = Field(default=3, ge=1)

    # ---- SLA targets in minutes: (response, resolution). Env form: SLA_HIGH=120,480
    sla_critical: SlaPair = (30, 240)
    sla_high: SlaPair = (120, 480)
    sla_medium: SlaPair = (480, 1440)
    sla_low: SlaPair = (1440, 4320)

    # ---- email (Phase 4)
    email_provider: Literal["smtp", "brevo", "resend", "console"] = "console"
    email_from: str = "Tasky <noreply@example.com>"
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = False  # 587: upgrade to TLS after connecting
    smtp_ssl: bool = False  # 465: TLS from the first byte
    brevo_api_key: str | None = None
    resend_api_key: str | None = None
    email_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # ---- worker
    run_worker_in_api: bool = False
    worker_poll_seconds: float = Field(default=5.0, gt=0, le=300)
    worker_batch_size: int = Field(default=20, ge=1, le=500)
    sla_check_seconds: float = Field(default=300.0, gt=0)
    # /health reports "stale" when the worker has not beaten for this long
    worker_stale_seconds: float = Field(default=120.0, gt=0)

    # ---- attachments (Phase 6)
    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: str = ".data/attachments"  # local backend; relative to the working dir
    s3_endpoint: str | None = None  # e.g. https://<project>.supabase.co/storage/v1/s3
    s3_region: str = "us-east-1"
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    max_upload_mb: int = Field(default=10, ge=1, le=100)
    download_url_seconds: int = Field(default=300, ge=10, le=3600)

    # ---- AI (Phase 7). none = features off (503 ai_disabled); rules = local, no network
    llm_provider: Literal["none", "rules", "groq", "gemini", "ollama"] = "none"
    llm_api_key: str | None = None
    llm_model: str | None = None  # default per provider, see app/ai/providers.py
    llm_base_url: str | None = None  # ollama, or any OpenAI-compatible endpoint
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    ai_rate_limit_per_min: int = Field(default=10, ge=1)
    ai_daily_limit: int = Field(default=500, ge=1)  # hard stop, well under free tiers
    ai_max_input_chars: int = Field(default=16000, ge=1000)  # ~4k tokens

    # ---- observability
    sentry_dsn: str | None = None
    metrics_enabled: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("sla_critical", "sla_high", "sla_medium", "sla_low", mode="before")
    @classmethod
    def _parse_sla(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",")]
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                raise ValueError("expected '<response_minutes>,<resolution_minutes>', e.g. 120,480")
            return (int(parts[0]), int(parts[1]))
        return value

    @field_validator("sla_critical", "sla_high", "sla_medium", "sla_low")
    @classmethod
    def _check_sla(cls, value: tuple[int, int]) -> tuple[int, int]:
        response, resolution = value
        if not 0 < response <= resolution:
            raise ValueError("SLA needs 0 < response <= resolution minutes")
        return value

    def sla_minutes(self, priority: str) -> tuple[int, int]:
        """(response, resolution) minutes for a priority value."""
        pair: tuple[int, int] = getattr(self, f"sla_{priority}")
        return pair

    @field_validator(
        "sentry_dsn",
        "cookie_secure",
        "log_json",
        "smtp_username",
        "smtp_password",
        "brevo_api_key",
        "resend_api_key",
        "s3_endpoint",
        "s3_bucket",
        "s3_access_key",
        "s3_secret_key",
        "llm_api_key",
        "llm_model",
        "llm_base_url",
        "google_client_id",
        "google_client_secret",
        "google_redirect_uri",
        "supabase_url",
        "supabase_service_role_key",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.is_production:
            if self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError(
                    "JWT_SECRET must be set to a random value of at least 32 characters "
                    "in production (e.g. `openssl rand -hex 32`)"
                )
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS may not contain '*' in production")
            if self.email_provider == "brevo" and not self.brevo_api_key:
                raise ValueError("EMAIL_PROVIDER=brevo needs BREVO_API_KEY")
            if self.email_provider == "resend" and not self.resend_api_key:
                raise ValueError("EMAIL_PROVIDER=resend needs RESEND_API_KEY")
            if self.storage_backend == "s3" and not (
                self.s3_endpoint and self.s3_bucket and self.s3_access_key and self.s3_secret_key
            ):
                raise ValueError(
                    "STORAGE_BACKEND=s3 needs S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY"
                )
            if self.llm_provider in ("groq", "gemini") and not self.llm_api_key:
                raise ValueError(f"LLM_PROVIDER={self.llm_provider} needs LLM_API_KEY")
            if self.allow_self_register and not self.rate_limit_enabled:
                raise ValueError(
                    "ALLOW_SELF_REGISTER=true in production requires RATE_LIMIT_ENABLED=true"
                )
        return self

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def supabase_auth_copy_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def google_callback_url(self) -> str:
        return self.google_redirect_uri or (
            f"{self.app_base_url.rstrip('/')}/api/v1/auth/google/callback"
        )

    @property
    def use_secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.app_env != "development"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def use_json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.app_env != "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
