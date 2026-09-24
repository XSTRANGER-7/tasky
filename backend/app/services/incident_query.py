"""GET /incidents: filters, search, sort and cursor pagination.

* **Search** (``q``): Postgres full-text (``websearch_to_tsquery`` over the generated,
  weighted ``search_vector``: title A, description B) OR trigram *word* similarity on
  the title (catches typos: "databse" finds "Database pool exhausted") OR a substring
  match; ``INC-142`` / ``142`` also match by number. ``sort=relevance`` orders by
  ts_rank + word similarity.
* **Sort**: allow-listed fields only, ``-`` for descending, comma-separated; ``id`` is
  always appended as a unique tie-breaker.
* **Pagination**: keyset. The cursor encodes the sort values of the last row, so pages
  are stable while new incidents arrive -- unlike page numbers, nothing shifts or repeats.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import ColumnElement, Float, and_, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.errors import InvalidInput
from app.db.base import utcnow
from app.models import Incident, IncidentAssignee, IncidentWatcher, Priority, Status, User
from app.models.incident import KEY_PATTERN
from app.services import permissions as perms
from app.services.team_scope import team_id_of

OPEN_WORK = (Status.OPEN, Status.IN_PROGRESS)
AT_RISK_WINDOW = timedelta(hours=1)
_KEY = re.compile(rf"^{KEY_PATTERN}$", re.IGNORECASE)

SlaFilter = Literal["breached", "at_risk", "on_track"]


@dataclass
class IncidentFilters:
    status: list[Status] = field(default_factory=list)
    priority: list[Priority] = field(default_factory=list)
    assignee: list[str] = field(default_factory=list)  # user id | "me" | "none"
    reporter: str | None = None  # user id | "me"
    q: str | None = None
    sla: SlaFilter | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    deleted: bool = False  # admins only: show the recycle bin instead
    watching: bool = False  # only incidents the caller watches


@dataclass(frozen=True)
class SortKey:
    name: str
    descending: bool
    expr: Any  # ORM attribute or SQL expression
    load: Callable[[Any], Any]  # JSON cursor value -> bind parameter


@dataclass
class Page:
    items: Sequence[Incident]
    next_cursor: str | None
    total: int


def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value))


# Column name -> (expression, cursor decoder). Everything here is NOT NULL.
_SORTABLE: dict[str, tuple[Any, Callable[[Any], Any]]] = {
    "created_at": (Incident.created_at, _dt),
    "updated_at": (Incident.updated_at, _dt),
    "resolution_due_at": (Incident.resolution_due_at, _dt),
    "priority": (Incident.priority, Priority),
    "status": (Incident.status, Status),
    "number": (Incident.number, int),
}


def _search_parts(q: str) -> tuple[ColumnElement[bool], ColumnElement[float]]:
    tsquery = func.websearch_to_tsquery("english", q)
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    matches: list[ColumnElement[bool]] = [
        Incident.search_vector.op("@@")(tsquery),
        # pg_trgm word similarity (q <% title, threshold 0.6): compares q with the best
        # matching *part* of the title, so a typo in one word of a long title still hits.
        literal(q).op("<%")(Incident.title),
        Incident.title.ilike(f"%{escaped}%", escape="\\"),
    ]
    key = _KEY.match(q.strip())
    if key:
        matches.append(Incident.number == int(key.group(1)))
    # float8 so the value round-trips exactly through the JSON cursor.
    rank = cast(func.ts_rank(Incident.search_vector, tsquery), Float) + cast(
        func.word_similarity(q, Incident.title), Float
    )
    return or_(*matches), rank


def parse_sort(
    raw: str | None, *, has_query: bool, rank: ColumnElement[float] | None
) -> list[SortKey]:
    spec = raw or ("relevance" if has_query else "-created_at")
    keys: list[SortKey] = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        descending = part.startswith("-")
        name = part.lstrip("-+")
        if name == "relevance":
            if rank is None:
                raise InvalidInput("sort=relevance needs a search query (q)", code="invalid_sort")
            # Relevance is always best-first; a leading "-" is accepted and ignored.
            keys.append(SortKey("relevance", True, rank, float))
            continue
        if name not in _SORTABLE:
            raise InvalidInput(
                f"Cannot sort by '{name}'",
                code="invalid_sort",
                details={"allowed": sorted([*_SORTABLE, "relevance"])},
            )
        if any(k.name == name for k in keys):
            continue
        expr, load = _SORTABLE[name]
        keys.append(SortKey(name, descending, expr, load))
    if not keys:
        raise InvalidInput("Empty sort", code="invalid_sort")
    keys.append(SortKey("id", keys[-1].descending, Incident.id, uuid.UUID))
    return keys


def _encode_cursor(keys: list[SortKey], row: Incident, rank: float | None) -> str:
    values: list[Any] = []
    for key in keys:
        if key.name == "relevance":
            values.append(rank)
        else:
            value = getattr(row, key.name)
            values.append(
                value.isoformat()
                if isinstance(value, datetime)
                else value.value
                if isinstance(value, Status | Priority)
                else str(value)
                if isinstance(value, uuid.UUID)
                else value
            )
    payload = json.dumps({"s": [k.name for k in keys], "v": values}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, keys: list[SortKey]) -> list[Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        if data["s"] != [k.name for k in keys] or len(data["v"]) != len(keys):
            raise ValueError("cursor does not match this sort")
        return [key.load(v) for key, v in zip(keys, data["v"], strict=True)]
    except (ValueError, KeyError, TypeError, binascii.Error, json.JSONDecodeError) as exc:
        raise InvalidInput(
            "Invalid cursor (it may belong to a different sort or filter)", code="invalid_cursor"
        ) from exc


def _after(keys: list[SortKey], values: list[Any]) -> ColumnElement[bool]:
    """Rows strictly after ``values`` in the sort order (mixed directions supported):
    (k1 > v1) OR (k1 = v1 AND k2 > v2) OR ... with > / < chosen per key direction."""
    clauses = []
    for i, key in enumerate(keys):
        equal_prefix = [keys[j].expr == values[j] for j in range(i)]
        beyond = key.expr < values[i] if key.descending else key.expr > values[i]
        clauses.append(and_(*equal_prefix, beyond))
    return or_(*clauses)


def _resolve_user(value: str, actor: User) -> uuid.UUID:
    if value == "me":
        return actor.id
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise InvalidInput(f"Unknown user filter '{value}'", code="invalid_filter") from exc


def build_where(filters: IncidentFilters, actor: User, now: datetime) -> list[ColumnElement[bool]]:
    if filters.deleted and not perms.is_admin(actor):
        raise InvalidInput("Only admins can list deleted tasks", code="invalid_filter")
    where: list[ColumnElement[bool]] = [
        Incident.team_id == team_id_of(actor),
        Incident.is_deleted.is_(filters.deleted),
    ]
    if filters.status:
        where.append(Incident.status.in_(filters.status))
    if filters.priority:
        where.append(Incident.priority.in_(filters.priority))
    if filters.assignee:
        options: list[ColumnElement[bool]] = []
        ids = [_resolve_user(a, actor) for a in filters.assignee if a != "none"]
        if ids:  # any of the task's assignees, not only the lead
            options.append(
                Incident.id.in_(
                    select(IncidentAssignee.incident_id).where(IncidentAssignee.user_id.in_(ids))
                )
            )
        if "none" in filters.assignee:
            options.append(Incident.assignee_id.is_(None))
        where.append(or_(*options))
    if filters.reporter:
        where.append(Incident.reporter_id == _resolve_user(filters.reporter, actor))
    if filters.watching:
        where.append(
            Incident.id.in_(
                select(IncidentWatcher.incident_id).where(IncidentWatcher.user_id == actor.id)
            )
        )
    if filters.category:
        where.append(func.lower(Incident.category) == filters.category.lower())
    if filters.tags:
        where.append(Incident.tags.contains([t.lower() for t in filters.tags]))
    if filters.sla:
        open_work = Incident.status.in_(OPEN_WORK)
        if filters.sla == "breached":
            where.append(and_(open_work, Incident.resolution_due_at < now))
        elif filters.sla == "at_risk":
            where.append(
                and_(
                    open_work,
                    Incident.resolution_due_at >= now,
                    Incident.resolution_due_at < now + AT_RISK_WINDOW,
                )
            )
        else:  # on_track
            where.append(and_(open_work, Incident.resolution_due_at >= now + AT_RISK_WINDOW))
    return where


async def search(
    session: AsyncSession,
    actor: User,
    filters: IncidentFilters,
    *,
    sort: str | None,
    cursor: str | None,
    limit: int,
) -> Page:
    now = utcnow()
    where = build_where(filters, actor, now)
    q = (filters.q or "").strip() or None
    rank: ColumnElement[float] | None = None
    if q:
        match, rank = _search_parts(q)
        where.append(match)

    keys = parse_sort(sort, has_query=q is not None, rank=rank)
    total = int(await session.scalar(select(func.count()).select_from(Incident).where(*where)) or 0)

    columns: list[Any] = [Incident]
    if rank is not None:
        columns.append(rank.label("rank"))
    stmt = (
        select(*columns)
        .where(*where)
        .options(
            joinedload(Incident.reporter),
            joinedload(Incident.assignee),
            selectinload(Incident.assignees),
        )
        .order_by(*[k.expr.desc() if k.descending else k.expr.asc() for k in keys])
        .limit(limit + 1)
    )
    if cursor:
        stmt = stmt.where(_after(keys, _decode_cursor(cursor, keys)))

    rows = (await session.execute(stmt)).unique().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [row[0] for row in rows]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(keys, last[0], float(last[1]) if rank is not None else None)
    return Page(items=items, next_cursor=next_cursor, total=total)
