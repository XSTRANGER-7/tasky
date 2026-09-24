"""LLM providers behind one interface (spec 10.1).

``complete(prompt, schema)`` returns a validated Pydantic object or raises. Groq,
Gemini and Ollama all speak the OpenAI chat-completions protocol, so one client covers
them. The scripted test double lives in ``tests/fakes.py``.

Failure handling: a 20 s timeout with one retry for transient errors (timeouts, 429,
5xx); invalid JSON or a schema mismatch is *not* retried -- it is rejected, logged and
the caller falls back to the rule-based answer.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)

DEFAULTS: dict[str, tuple[str, str]] = {
    # provider: (base URL, model)
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
    "ollama": ("http://localhost:11434/v1", "llama3.1"),
}


class AIUnavailable(Exception):
    """The provider could not answer in time (network, timeout, rate limit, 5xx)."""


class InvalidOutput(Exception):
    """The provider answered, but not with JSON matching the schema."""


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    user: str


@dataclass
class Completion[M: BaseModel]:
    value: M
    model: str
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, prompt: Prompt, schema: type[T]) -> Completion[T]: ...


def parse[M: BaseModel](content: str, schema: type[M]) -> M:
    """Model text -> validated object. Tolerates a ```json fence, nothing else."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise InvalidOutput(f"not JSON: {exc}") from exc
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise InvalidOutput(f"schema mismatch: {exc.error_count()} errors") from exc


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout: float,
        client: httpx.AsyncClient | None = None,
        retry_delay: float = 1.0,
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retry_delay = retry_delay
        self._client = client

    async def _post(self, body: dict[str, object]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            return await client.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def complete(self, prompt: Prompt, schema: type[T]) -> Completion[T]:
        body: dict[str, object] = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
        }
        started = time.perf_counter()
        last: Exception | None = None
        for attempt in (1, 2):
            try:
                res = await self._post(body)
            except httpx.HTTPError as exc:
                last = exc
            else:
                if res.status_code == 200:
                    break
                last = AIUnavailable(f"HTTP {res.status_code}")
                if res.status_code not in (408, 429) and res.status_code < 500:
                    raise AIUnavailable(f"{self.name}: HTTP {res.status_code}")
            if attempt == 1:
                await asyncio.sleep(self.retry_delay)
        else:
            raise AIUnavailable(f"{self.name}: {type(last).__name__}: {last}")

        payload = res.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidOutput("no message content") from exc
        usage = payload.get("usage") or {}
        return Completion(
            value=parse(content, schema),
            model=str(payload.get("model") or self.model),
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )


def build_provider(settings: Settings) -> LLMProvider | None:
    """None for ``none`` and ``rules`` (no network)."""
    if settings.llm_provider in ("none", "rules"):
        return None
    base, model = DEFAULTS[settings.llm_provider]
    return OpenAICompatibleProvider(
        settings.llm_provider,
        base_url=settings.llm_base_url or base,
        model=settings.llm_model or model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
    )


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fenced(label: str, text: str) -> str:
    """User-supplied text in a clearly delimited block the instructions refer to."""
    safe = text.replace("<<<", "< < <").replace(">>>", "> > >")  # cannot close the fence
    return f"<<<{label}\n{safe}\n>>>"
