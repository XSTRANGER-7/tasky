"""Running with real data: the sign-in page options, the first admin, and the demo
seed refusing a production database."""

from __future__ import annotations

import os
import subprocess
import sys

import httpx

from tests.conftest import TEST_JWT_SECRET, BuildApp, client_for


async def test_auth_config_is_public_and_follows_settings(build_app: BuildApp) -> None:
    async with client_for(build_app(demo_mode=True, allow_self_register=False)) as c:
        res = await c.get("/api/v1/auth/config")
    assert res.status_code == 200
    assert res.json() == {
        "allow_self_register": False,
        "demo_mode": True,
        "google_enabled": False,
    }


async def test_demo_mode_is_off_by_default(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/config")).json()["demo_mode"] is False


def test_seed_refuses_a_production_database() -> None:
    env = {
        "APP_ENV": "production",
        "JWT_SECRET": TEST_JWT_SECRET,
        "CORS_ORIGINS": "https://app.example.com",
        "DATABASE_URL": "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none",
    }

    result = subprocess.run(
        [sys.executable, "-m", "app.scripts.seed"],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "Refusing to seed demo data into a production database" in result.stderr
