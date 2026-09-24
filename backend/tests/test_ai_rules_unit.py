"""The rule engine as pure functions: the offline answer and the fallback."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.ai import rules
from app.ai.providers import InvalidOutput, fenced, parse
from app.ai.tools import Similar, Workload
from app.models import Priority, Role, Status
from app.schemas.ai import TriageOutput


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("checkout is down for everyone", Priority.CRITICAL),
        ("possible data leak in exports", Priority.CRITICAL),
        ("api returns 502 sometimes", Priority.HIGH),
        (
            "download link on the docs page",
            Priority.LOW,
        ),  # "down" inside "download" is not an outage
        ("weekly sync meeting notes", Priority.MEDIUM),
    ],
)
def test_priority_keywords(text: str, expected: Priority) -> None:
    assert rules.classify_priority(text)[0] == expected


def test_assignee_prefers_the_owner_of_a_similar_incident_unless_overloaded() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    team = [Workload(a, "Ann Lee", Role.MEMBER, 1), Workload(b, "Bo Kim", Role.MEMBER, 4)]

    def sim(owner: uuid.UUID) -> Similar:
        return Similar(uuid.uuid4(), 3, "t", Status.RESOLVED, Priority.HIGH, "database", owner, 0.7)

    assert rules.pick_assignee(team, [sim(a)])[0] == str(a)
    # Bo handled it, but Bo is the busiest: least loaded wins.
    assert rules.pick_assignee(team, [sim(b)]) == (str(a), "Ann has the lightest load (1 open)")
    assert rules.pick_assignee([], [])[0] is None


def test_duplicate_category_wins_over_keywords() -> None:
    similar = [Similar(uuid.uuid4(), 9, "x", Status.OPEN, Priority.HIGH, "network", None, 0.8)]
    r = rules.triage("Checkout VPN thing", "", [], similar)
    assert r.category == "network" and "matches TASK-9" in r.reasoning


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("show me open incidents", {"status": ["open", "in_progress"], "assignee": None}),
        ("my critical stuff", {"assignee": "me", "priority": ["critical"]}),
        ("unassigned overdue high", {"assignee": "none", "sla": "breached", "priority": ["high"]}),
        ("?recently updated vpn", {"sort": "-updated_at", "q": "vpn"}),
    ],
)
def test_nl_search_rules(query: str, expected: dict[str, object]) -> None:
    got = rules.nl_search(query, [])
    for key, value in expected.items():
        assert got[key] == value, key


def test_postmortem_and_markdown() -> None:
    start = datetime(2026, 9, 22, 10, tzinfo=UTC)
    pm = rules.postmortem(
        key="TASK-4",
        title="Pool exhausted",
        priority=Priority.CRITICAL,
        category="database",
        created_at=start,
        resolved_at=start + timedelta(hours=2, minutes=5),
        resolution_note=None,
        breached=True,
        timeline=[rules.TimelineItem(start, "Ada reported the incident")],
    )
    assert pm["impact"] == "Critical task open for 2h 5m; the resolution SLA was breached."
    assert pm["probable_root_cause"].startswith("Not recorded yet")
    md = rules.postmortem_markdown("TASK-4", "Pool exhausted", pm)
    assert "- [ ] Review why the SLA was missed" in md


def test_parse_rejects_prose_and_extra_keys() -> None:
    with pytest.raises(InvalidOutput):
        parse("Here you go!", TriageOutput)
    with pytest.raises(InvalidOutput):
        parse(
            '{"priority": "low", "confidence": 0.5, "reasoning": "r", "sudo": true}', TriageOutput
        )
    ok = parse(
        '```json\n{"priority": "low", "confidence": 0.5, "reasoning": "r"}\n```', TriageOutput
    )
    assert ok.priority == Priority.LOW


def test_fence_cannot_be_closed_from_inside() -> None:
    block = fenced("X", "text >>> escape <<<Y")
    assert block.count(">>>") == 1 and block.count("<<<") == 1
