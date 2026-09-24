"""/api/v1/dashboard -- aggregate numbers for the dashboard page."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import DbSession, TeamUser
from app.schemas.dashboard import DashboardSummary
from app.services import dashboard_service
from app.services.team_scope import team_id_of

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Dashboard summary",
    description="Counts, SLA, MTTR, 14-day trend and recent activity for the active team. "
    "Cached for 30 s and invalidated by any change to that team's incidents.",
)
async def get_summary(session: DbSession, actor: TeamUser) -> DashboardSummary:
    return await dashboard_service.summary(session, team_id_of(actor))
