# ADR 0007 - AI suggests, never acts; a rule engine is always there

- Status: accepted
- Date: 2026-09-22

## Context

The assignment rewards AI features, but an incident tool is exactly where a wrong
automatic change hurts: a mis-prioritised outage, a ticket assigned to someone on leave,
a hallucinated "duplicate". Free LLM tiers rate-limit, time out and change models. The
demo must work with no API key at all.

## Decision

1. **Suggest, never act.** Every AI output is stored in `ai_suggestions` (kind, payload,
   engine, model, prompt version, latency, tokens) and shown with Accept / Dismiss.
   Accepting applies the change through the normal services, so permissions, validation
   and the audit trail are the same as for a human click. An `ai_applied` event records
   that it came from a suggestion.
2. **Three engines behind one switch** (`LLM_PROVIDER`):
   - `none`: features off; `/ai/*` answers 503 `ai_disabled`; the UI hides the panels.
   - `rules`: a deterministic engine that is offline, free, instant and explainable. It
     does keyword severity, category, least-loaded or previous-owner assignee, trigram
     duplicates, extractive summaries, a templated postmortem and a keyword query parser.
   - `groq` / `gemini` / `ollama`: one OpenAI-compatible client. The rule engine is
     still the fallback on timeout, 429/5xx, invalid output or an exhausted daily budget,
     and the UI shows a quiet "AI unavailable" chip.
3. **Structured output only.** The model must return JSON matching a Pydantic schema
   with `extra="forbid"`. Anything else is rejected and logged, never shown. IDs in the
   answer (assignee, similar incidents, search assignee) are checked against the
   database, and the category against the known list.
4. **Least privilege for the model.** It sees only two read-only queries (similar
   incidents, team workload) and the incident's own text. No emails, tokens or hashes;
   no attachments; internal notes only when the requesting user may see them. User text
   is fenced as data (`<<<LABEL ... >>>`, with fence markers escaped), and the
   instructions say to treat it as untrusted.
5. **Cost and abuse limits**: 10 calls per user per minute, a daily cap per process (then
   rules), a ~4k-token input cap, and a 20 s timeout with one retry.

## Consequences

- The app is complete and demonstrable with `LLM_PROVIDER=rules` and no network. A
  model improves suggestions but is never required.
- The rule engine is the baseline in the eval harness (`backend/evals`). Its first
  honest run: priority 13/20 exact (19/20 within one level), category 17/20. The labels
  were written before the rules were run, and the rules were not tuned to them.
- Accept and dismiss rates per feature are visible to admins, which is the real signal
  for whether a feature helps.
- Natural-language search never runs SQL. It produces the same filter parameters a
  person would click, sent to the same validated endpoint.
