"""Deterministic, offline answers for every AI feature.

Used as the whole engine with ``LLM_PROVIDER=rules`` and as the fallback whenever a
model is slow, down or returns garbage. Keeping it good matters: it is what users see
when the free tier runs out, and it is the baseline the eval harness compares against.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.ai.tools import DUPLICATE_THRESHOLD, Similar, Workload
from app.models import Priority, Status

CATEGORIES = (
    "payments",
    "database",
    "auth",
    "messaging",
    "infrastructure",
    "frontend",
    "network",
    "search",
    "mobile",
    "integrations",
    "reporting",
    "monitoring",
)

# First match wins, most severe first. Word-boundary regexes, so "down" != "download".
PRIORITY_RULES: tuple[tuple[Priority, tuple[str, ...]], ...] = (
    (
        Priority.CRITICAL,
        (
            r"\boutage\b",
            r"\b(site|service|prod(uction)?|api|app|everything|checkout|login) (is )?down\b",
            r"\bdown for (all|every)",
            r"\ball (users|customers)\b",
            r"\bdata (loss|leak)\b",
            r"\b(security|breach|compromised|ransomware)\b",
            r"\bcannot (log ?in|sign ?in|pay|checkout)\b",
            r"\bexhausted\b",
            r"\bcorrupt(ed|ion)?\b",
            r"\bsev ?1\b|\bp1\b",
        ),
    ),
    (
        Priority.HIGH,
        (
            r"\b5\d\d\b",
            r"\b(error|errors|failing|fails|failed|failure|crash(es|ing)?)\b",
            r"\btime ?outs?\b|\btimed out\b",
            r"\b(degraded|slow|latency|spik(e|es|ing))\b",
            r"\bexpir(es|ing|ed)\b",
            r"\bnot (delivered|sent|working|loading)\b",
            r"\bsev ?2\b|\bp2\b",
        ),
    ),
    (
        Priority.LOW,
        (
            r"\b(typo|cosmetic|misaligned|alignment|colou?r|wording|copy change)\b",
            r"\b(question|how do i|feature request|nice to have|docs?|documentation)\b",
            r"\b(minor|small|tooltip|icon)\b",
            r"\bsev ?4\b|\bp4\b",
        ),
    ),
)

CATEGORY_RULES: dict[str, tuple[str, ...]] = {
    "payments": ("payment", "checkout", "stripe", "card", "invoice", "refund", "billing", "charge"),
    "database": (
        "database",
        "db ",
        "postgres",
        "mysql",
        "query",
        "replica",
        "connection pool",
        "deadlock",
        "migration",
        "orders-db",
    ),
    "auth": (
        "login",
        "log in",
        "sign in",
        "password",
        "sso",
        "2fa",
        "mfa",
        "oauth",
        "session",
        "token",
        "saml",
    ),
    "messaging": (
        "email",
        "e-mail",
        "smtp",
        "outlook",
        "gmail",
        "sms",
        "notification",
        "newsletter",
        "mail",
    ),
    "infrastructure": (
        "disk",
        "cpu",
        "memory",
        "kubernetes",
        "k8s",
        "pod",
        "node",
        "certificate",
        "tls",
        "ssl",
        "backup",
        "server",
        "deploy",
        "container",
    ),
    "frontend": (
        "ui",
        "button",
        "page",
        "css",
        "layout",
        "browser",
        "chart",
        "dashboard",
        "render",
        "timezone",
        "utc",
    ),
    "network": ("vpn", "dns", "network", "firewall", "packet", "proxy", "wifi", "latency"),
    "search": ("search", "elasticsearch", "index", "autocomplete", "results"),
    "mobile": ("ios", "android", "mobile", "app store", "push notification"),
    "integrations": (
        "webhook",
        "slack",
        "jira",
        "salesforce",
        "integration",
        "third-party",
        "partner api",
        "sync",
    ),
    "reporting": ("report", "export", "csv", "analytics", "metrics report"),
    "monitoring": ("alert", "monitoring", "grafana", "prometheus", "pager", "on-call", "logging"),
}


def _text(*parts: str | None) -> str:
    return " ".join(p for p in parts if p).lower()


@dataclass(frozen=True)
class RuleTriage:
    priority: Priority
    category: str | None
    suggested_assignee_id: str | None
    confidence: float
    reasoning: str


def classify_priority(text: str) -> tuple[Priority, str | None]:
    for priority, patterns in PRIORITY_RULES:
        for pattern in patterns:
            if match := re.search(pattern, text):
                return priority, match.group(0)
    return Priority.MEDIUM, None


def classify_category(text: str) -> tuple[str | None, str | None]:
    padded = f" {text} "
    best: tuple[int, str, str] | None = None
    for category, words in CATEGORY_RULES.items():
        hits = [w for w in words if w in padded]
        if hits and (best is None or len(hits) > best[0]):
            best = (len(hits), category, hits[0])
    return (best[1], best[2]) if best else (None, None)


def pick_assignee(
    workload: Sequence[Workload], similar: Sequence[Similar]
) -> tuple[str | None, str]:
    """Whoever handled the closest similar incident, unless they are the busiest person
    on the team; otherwise the least loaded member."""
    if not workload:
        return None, "nobody is available to assign"
    by_id = {w.user_id: w for w in workload}
    busiest = max(w.open_count for w in workload)
    for s in similar:
        owner = by_id.get(s.assignee_id) if s.assignee_id else None
        if owner and (owner.open_count < busiest or len(workload) == 1):
            return str(owner.user_id), f"{owner.name.split()[0]} handled the similar {s.key}"
    least = workload[0]
    return str(
        least.user_id
    ), f"{least.name.split()[0]} has the lightest load ({least.open_count} open)"


def triage(
    title: str, description: str, workload: Sequence[Workload], similar: Sequence[Similar]
) -> RuleTriage:
    text = _text(title, description)
    priority, why_p = classify_priority(text)
    category, why_c = classify_category(text)
    # A near-identical earlier incident is strong evidence for its category.
    top = similar[0] if similar else None
    if top and top.score >= DUPLICATE_THRESHOLD and top.category:
        category, why_c = top.category, f"matches {top.key}"
    assignee, why_a = pick_assignee(workload, similar)
    reasons = [
        f"priority {priority.value}"
        + (f' because of "{why_p}"' if why_p else " (no severity keywords)"),
        f"category {category}" + (f' ("{why_c}")' if why_c else "")
        if category
        else "category unclear",
        why_a,
    ]
    confidence = 0.35 + (0.2 if why_p else 0) + (0.15 if why_c else 0)
    return RuleTriage(
        priority, category, assignee, round(min(confidence, 0.75), 2), "; ".join(reasons) + "."
    )


# ---------------------------------------------------------------- summaries


@dataclass(frozen=True)
class ThreadItem:
    author: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class TimelineItem:
    at: datetime
    text: str


def _clip(text: str, n: int = 140) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def summarize(
    *,
    key: str,
    title: str,
    status: Status,
    priority: Priority,
    assignee: str | None,
    comments: Sequence[ThreadItem],
    now: datetime,
) -> dict[str, object]:
    people = sorted({c.author for c in comments})
    latest = comments[-1] if comments else None
    status_line = {
        Status.OPEN: "Open and waiting for someone to start work",
        Status.IN_PROGRESS: "In progress",
        Status.RESOLVED: "Resolved, awaiting confirmation",
        Status.CLOSED: "Closed",
    }[status]
    if assignee:
        status_line += f" (assigned to {assignee})"
    summary = f"{key} ({priority.value}): {title}. "
    summary += (
        f"{len(comments)} comments from {', '.join(people)}." if comments else "No discussion yet."
    )
    if latest:
        summary += f' Latest from {latest.author}: "{_clip(latest.body)}"'
    questions = [
        f"{c.author}: {_clip(q.strip(), 160)}"
        for c in comments[-10:]
        for q in re.findall(r"([^.?!\n]{8,}\?)", c.body)[:1]
    ][-3:]
    return {"summary": summary, "current_status": status_line + ".", "open_questions": questions}


ACTIONS_BY_CATEGORY = {
    "payments": "Add a synthetic checkout probe per region with an alert on error rate.",
    "database": "Alert on connection-pool saturation and slow queries before users notice.",
    "auth": "Add an end-to-end login check to the uptime monitor.",
    "messaging": "Monitor delivery and bounce rates per mailbox provider.",
    "infrastructure": (
        "Automate the check that would have caught this (expiry, capacity, backup window)."
    ),
    "frontend": "Add a regression test and a visual check for the affected screen.",
    "network": "Capture the failing path in a runbook with the diagnostic commands.",
}


def postmortem(
    *,
    key: str,
    title: str,
    priority: Priority,
    category: str | None,
    created_at: datetime,
    resolved_at: datetime | None,
    resolution_note: str | None,
    breached: bool,
    timeline: Sequence[TimelineItem],
) -> dict[str, object]:
    end = resolved_at or (timeline[-1].at if timeline else created_at)
    minutes = max(0, int((end - created_at).total_seconds() // 60))
    duration = f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"
    impact = f"{priority.value.capitalize()} task open for {duration}"
    impact += "; the resolution SLA was breached." if breached else "; resolved within SLA."
    actions = [
        ACTIONS_BY_CATEGORY.get(category or "", "Add monitoring that would detect this earlier."),
        "Write down the fix as a runbook step so the next responder is faster.",
    ]
    if breached:
        actions.append("Review why the SLA was missed: detection, assignment or fix time.")
    return {
        "timeline": [f"{t.at.strftime('%d %b %H:%M')} UTC - {t.text}" for t in timeline][:15],
        "probable_root_cause": (
            _clip(resolution_note, 400) if resolution_note else "Not recorded yet: add it here."
        ),
        "impact": impact,
        "action_items": actions,
    }


def postmortem_markdown(key: str, title: str, pm: dict[str, object]) -> str:
    def items(value: object) -> Iterable[str]:
        return [str(v) for v in value] if isinstance(value, list) else []

    lines = [f"## Postmortem: {key} {title}", "", "### Impact", str(pm.get("impact", "")), ""]
    lines += ["### Timeline", *[f"- {t}" for t in items(pm.get("timeline"))], ""]
    lines += ["### Probable root cause", str(pm.get("probable_root_cause", "")), ""]
    lines += ["### Action items", *[f"- [ ] {a}" for a in items(pm.get("action_items"))]]
    return "\n".join(lines)


# ---------------------------------------------------------------- natural-language search

STATUS_WORDS = {
    Status.OPEN: (r"\bopen\b", r"\bnew\b", r"\bunstarted\b"),
    Status.IN_PROGRESS: (r"\bin[ -]progress\b", r"\bworking\b", r"\bactive\b", r"\bongoing\b"),
    Status.RESOLVED: (r"\bresolved\b", r"\bfixed\b", r"\bdone\b"),
    Status.CLOSED: (r"\bclosed\b",),
}
PRIORITY_WORDS = {
    Priority.CRITICAL: (r"\bcritical\b", r"\bsev ?1\b", r"\bp1\b", r"\burgent\b"),
    Priority.HIGH: (r"\bhigh\b", r"\bsev ?2\b", r"\bp2\b"),
    Priority.MEDIUM: (r"\bmedium\b", r"\bsev ?3\b", r"\bp3\b"),
    Priority.LOW: (r"\blow\b", r"\bsev ?4\b", r"\bp4\b", r"\bminor\b"),
}
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "for",
        "to",
        "in",
        "on",
        "with",
        "me",
        "my",
        "mine",
        "show",
        "find",
        "list",
        "all",
        "any",
        "tasks",
        "task",
        "incidents",
        "incident",
        "issues",
        "issue",
        "tickets",
        "ticket",
        "that",
        "are",
        "is",
        "which",
        "what",
        "where",
        "who",
        "please",
        "about",
        "from",
        "by",
        "assigned",
        "unassigned",
        "nobody",
        "anyone",
        "sla",
        "breached",
        "overdue",
        "late",
        "risk",
        "due",
        "soon",
        "at",
        "oldest",
        "newest",
        "latest",
        "recent",
        "first",
        "last",
        "sorted",
        "sort",
        "priority",
        "status",
    ]
)


def nl_search(query: str, team: Sequence[tuple[str, str]]) -> dict[str, object]:
    """Free text -> filters for GET /incidents. ``team`` is (user_id, name) pairs."""
    q = query.lower().strip().lstrip("?").strip()
    out: dict[str, object] = {
        "status": [],
        "priority": [],
        "assignee": None,
        "sla": None,
        "q": None,
        "sort": None,
    }
    consumed: list[str] = []

    def take(pattern: str) -> bool:
        if m := re.search(pattern, q):
            consumed.append(m.group(0))
            return True
        return False

    statuses = [s for s, pats in STATUS_WORDS.items() if any(take(p) for p in pats)]
    # "Open incidents" in everyday speech means unresolved, not only never started.
    if statuses == [Status.OPEN] and re.search(r"\bopen\b", q):
        statuses = [Status.OPEN, Status.IN_PROGRESS]
    out["status"] = [s.value for s in statuses]
    out["priority"] = [
        p.value for p, pats in PRIORITY_WORDS.items() if any(take(p_) for p_ in pats)
    ]

    if take(r"\b(unassigned|nobody|no one|no assignee)\b"):
        out["assignee"] = "none"
    elif take(r"\b(assigned to me|for me|my|mine)\b"):  # not a bare "me": "show me ..."
        out["assignee"] = "me"
    else:
        for user_id, name in team:
            first = name.split()[0].lower()
            if take(rf"\b{re.escape(first)}('s)?\b"):
                out["assignee"] = user_id
                break

    if take(r"\b(breached|overdue|late|past due|missed sla)\b"):
        out["sla"] = "breached"
    elif take(r"\b(at risk|due soon|about to breach)\b"):
        out["sla"] = "at_risk"

    if take(r"\boldest\b"):
        out["sort"] = "created_at"
    elif take(r"\b(most urgent|by priority|highest priority)\b"):
        out["sort"] = "-priority,-created_at"
    elif take(r"\b(recently updated|last updated)\b"):
        out["sort"] = "-updated_at"
    elif take(r"\b(newest|latest|recent)\b"):
        out["sort"] = "-created_at"

    rest = q
    for c in consumed:
        rest = rest.replace(c, " ")
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9._-]*", rest) if w not in STOPWORDS]
    out["q"] = " ".join(words) or None
    return out
