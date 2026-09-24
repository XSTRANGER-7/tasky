"""/api/v1/admin/settings: the effective runtime configuration, read-only.

Settings come from the environment (12-factor) and are validated at startup, so the
admin UI shows them rather than editing them: a change is a deploy, which keeps every
running process consistent and leaves an audit trail in version control.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import __version__
from app.core.deps import AppSettings, DbSession, get_team_admin
from app.models import Priority
from app.schemas.notification import WorkerStatus
from app.services.worker_status import worker_status

# Team admins see the (read-only, secret-free) runtime configuration their team runs on.
router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(get_team_admin)])


class SlaTarget(BaseModel):
    priority: Priority
    response_minutes: int
    resolution_minutes: int


class FeatureFlag(BaseModel):
    key: str
    label: str
    enabled: bool
    detail: str


class AdminSettings(BaseModel):
    version: str
    git_sha: str
    environment: str
    sla: list[SlaTarget]
    email_provider: str
    email_from: str
    sla_check_seconds: float
    worker: WorkerStatus
    flags: list[FeatureFlag]


@router.get("/settings", response_model=AdminSettings, summary="Effective settings (team admins)")
async def get_settings(session: DbSession, settings: AppSettings) -> AdminSettings:
    sla = []
    for priority in reversed(Priority):  # most urgent first
        response, resolution = settings.sla_minutes(priority.value)
        sla.append(
            SlaTarget(priority=priority, response_minutes=response, resolution_minutes=resolution)
        )
    return AdminSettings(
        version=__version__,
        git_sha=settings.git_sha,
        environment=settings.app_env,
        sla=sla,
        email_provider=settings.email_provider,
        email_from=settings.email_from,
        sla_check_seconds=settings.sla_check_seconds,
        worker=await worker_status(session, settings),
        flags=[
            FeatureFlag(
                key="email",
                label="Email notifications",
                enabled=settings.email_provider != "console",
                detail=f"Provider: {settings.email_provider}"
                + (" (logged, not sent)" if settings.email_provider == "console" else ""),
            ),
            FeatureFlag(
                key="worker_in_api",
                label="Worker inside the API process",
                enabled=settings.run_worker_in_api,
                detail="Single-container hosting; normally the worker runs on its own",
            ),
            FeatureFlag(
                key="metrics",
                label="Prometheus metrics",
                enabled=settings.metrics_enabled,
                detail="/metrics, reachable only on the private network",
            ),
            FeatureFlag(
                key="ai",
                label="AI assistance",
                enabled=settings.llm_provider != "none",
                detail={
                    "none": "Off (LLM_PROVIDER=none); the app is complete without it",
                    "rules": "Rule-based engine: offline, no data leaves the server",
                }.get(
                    settings.llm_provider,
                    f"{settings.llm_provider} ({settings.llm_model or 'default model'}), "
                    "rules as fallback",
                ),
            ),
        ],
    )
