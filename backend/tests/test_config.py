from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_JWT_SECRET, Settings

STRONG_SECRET = "a" * 64


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests assert on defaults, so the runner's env (CI sets APP_ENV etc.) must
    not leak in."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_defaults_are_safe_for_local_development() -> None:
    s = _settings()

    assert s.app_env == "development"
    assert s.cors_origins == ["http://localhost:5173"]
    assert not s.is_production
    assert s.use_json_logs is False


def test_cors_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.vercel.app, https://b.example ,")

    assert _settings().cors_origins == ["https://a.vercel.app", "https://b.example"]


def test_blank_sentry_dsn_means_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "")

    assert _settings().sentry_dsn is None


@pytest.mark.parametrize("secret", [DEFAULT_JWT_SECRET, "too-short"])
def test_production_refuses_weak_jwt_secret(secret: str) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _settings(app_env="production", jwt_secret=secret)


def test_production_refuses_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        _settings(app_env="production", jwt_secret=STRONG_SECRET, cors_origins=["*"])


def test_production_with_strong_secret_is_accepted() -> None:
    s = _settings(app_env="production", jwt_secret=STRONG_SECRET)

    assert s.is_production
    assert s.use_json_logs is True


def test_explicit_log_format_wins() -> None:
    s = _settings(app_env="production", jwt_secret=STRONG_SECRET, log_json=False)

    assert s.use_json_logs is False


@pytest.mark.parametrize("var", ["COOKIE_SECURE", "LOG_JSON"])
def test_blank_optional_bools_mean_automatic(monkeypatch: pytest.MonkeyPatch, var: str) -> None:
    monkeypatch.setenv(var, "")

    assert getattr(_settings(), var.lower()) is None


def test_secure_cookies_follow_environment() -> None:
    assert _settings().use_secure_cookies is False  # development: plain http://localhost
    assert _settings(app_env="test").use_secure_cookies is True
    assert _settings(cookie_secure=False, app_env="test").use_secure_cookies is False


def test_production_self_register_requires_rate_limits() -> None:
    with pytest.raises(ValidationError, match="RATE_LIMIT_ENABLED"):
        _settings(app_env="production", jwt_secret=STRONG_SECRET, rate_limit_enabled=False)


def test_sla_parsed_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLA_HIGH", "60, 300")

    assert _settings().sla_minutes("high") == (60, 300)
    assert _settings().sla_minutes("critical") == (30, 240)


@pytest.mark.parametrize("raw", ["60", "a,b", "300,60", "0,10"])
def test_sla_rejects_bad_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("SLA_LOW", raw)

    with pytest.raises(ValidationError):
        _settings()
