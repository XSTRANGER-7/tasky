# ADR 0001 - Record architecture decisions

- Status: accepted
- Date: 2026-09-22

## Context

Reviewers and interviewers ask *why*, not only *what*. Decisions made under time
pressure are easy to forget and hard to defend later.

## Decision

Significant decisions are recorded as short ADRs in `docs/adr/`, numbered, one per
file: context, decision, consequences. An ADR is never edited after acceptance; a new
ADR supersedes it.

Planned ADRs from the spec: transactional outbox vs a queue, SSE vs WebSockets, soft
delete, JWT access + rotating refresh vs server sessions.

## Consequences

A few minutes per decision; written reasoning to point at in review.
