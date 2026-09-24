"""Test doubles for the two outside services: email delivery and the LLM.

They live here, not in ``app/``, so production code only contains real integrations.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.ai.providers import AIUnavailable, Completion, Prompt, parse
from app.notifications.senders import Email, SendError


@dataclass
class FakeSender:
    """Records sends; fails the first ``fail_times`` calls; optional delay."""

    fail_times: int = 0
    delay: float = 0.0
    sent: list[Email] = field(default_factory=list)
    calls: int = 0
    name: str = "fake"

    async def send(self, email: Email) -> None:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.calls <= self.fail_times:
            raise SendError(f"fake failure {self.calls}")
        self.sent.append(email)


@dataclass
class FakeProvider:
    """Scripted LLM: each call pops the next item. A string is parsed like real model
    output, an exception is raised, a dict is serialised first."""

    responses: list[object] = field(default_factory=list)
    name: str = "fake"
    model: str = "fake-1"
    prompts: list[Prompt] = field(default_factory=list)

    async def complete[T: BaseModel](self, prompt: Prompt, schema: type[T]) -> Completion[T]:
        self.prompts.append(prompt)
        if not self.responses:
            raise AIUnavailable("fake: no scripted response")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return Completion(
            value=parse(text, schema), model=self.model, latency_ms=5, tokens_in=100, tokens_out=40
        )
