"""Triage evaluation harness (spec 10.4).

Runs triage over evals/incidents.jsonl (20 hand-labelled incidents) and prints accuracy
for priority and category plus a priority confusion matrix.

    python -m evals.triage_eval                    # rule-based engine (no network)
    LLM_PROVIDER=groq LLM_API_KEY=... python -m evals.triage_eval --engine llm

The labels were written before the rules were run against them; do not tune the rules
to this file, or the number stops meaning anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.ai import prompts, rules
from app.ai.providers import AIUnavailable, InvalidOutput, build_provider
from app.core.config import get_settings
from app.models import Priority
from app.schemas.ai import TriageOutput

DATA = Path(__file__).with_name("incidents.jsonl")
LEVELS = [p.value for p in (Priority.CRITICAL, Priority.HIGH, Priority.MEDIUM, Priority.LOW)]


@dataclass
class Case:
    title: str
    description: str
    priority: str
    category: str


@dataclass
class Result:
    case: Case
    priority: str
    category: str | None
    error: str | None = None


def load() -> list[Case]:
    return [
        Case(**json.loads(line)) for line in DATA.read_text(encoding="utf-8").splitlines() if line
    ]


async def run(engine: str) -> list[Result]:
    cases = load()
    if engine == "rules":
        out = []
        for c in cases:
            r = rules.triage(c.title, c.description, [], [])
            out.append(Result(c, r.priority.value, r.category))
        return out

    settings = get_settings()
    provider = build_provider(settings)
    if provider is None:
        sys.exit("--engine llm needs LLM_PROVIDER=groq|gemini|ollama (and LLM_API_KEY)")
    results = []
    for c in cases:
        prompt = prompts.triage(c.title, c.description, [], [], settings.ai_max_input_chars)
        try:
            done = await provider.complete(prompt, TriageOutput)
            results.append(
                Result(c, done.value.priority.value, (done.value.category or "").lower() or None)
            )
        except (AIUnavailable, InvalidOutput) as exc:
            # Counted as wrong: in the app this would fall back to the rules.
            results.append(Result(c, "-", None, error=str(exc)))
    return results


def report(results: list[Result], engine: str) -> str:
    n = len(results)
    p_ok = sum(r.priority == r.case.priority for r in results)
    c_ok = sum(r.category == r.case.category for r in results)
    # Off by one level (critical vs high, etc.) is a smaller mistake than off by two.
    near = sum(
        r.priority in LEVELS and abs(LEVELS.index(r.priority) - LEVELS.index(r.case.priority)) <= 1
        for r in results
    )
    matrix = Counter((r.case.priority, r.priority) for r in results)
    lines = [
        f"Triage eval - engine: {engine}, {n} incidents",
        "",
        f"priority accuracy : {p_ok}/{n} ({p_ok / n:.0%})",
        f"  within one level: {near}/{n} ({near / n:.0%})",
        f"category accuracy : {c_ok}/{n} ({c_ok / n:.0%})",
        "",
        "priority confusion (rows = expected, columns = predicted)",
        "            " + "".join(f"{p:>10}" for p in LEVELS),
    ]
    for expected in LEVELS:
        lines.append(
            f"{expected:>10}  " + "".join(f"{matrix[(expected, got)]:>10}" for got in LEVELS)
        )
    misses = [r for r in results if r.priority != r.case.priority or r.category != r.case.category]
    if misses:
        lines += ["", "misses:"]
        for r in misses:
            lines.append(
                f"  - {r.case.title[:48]:<48} priority {r.case.priority}->{r.priority}"
                f", category {r.case.category}->{r.category}"
                + (f"  [{r.error}]" if r.error else "")
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--engine", choices=["rules", "llm"], default="rules")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(report(asyncio.run(run(args.engine)), args.engine))


if __name__ == "__main__":
    main()
