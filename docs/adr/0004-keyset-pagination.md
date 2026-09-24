# ADR 0004 - Keyset (cursor) pagination for the incident list

- Status: accepted
- Date: 2026-09-22

## Context

The incident list is sorted (newest first by default, or by priority, SLA due time, ...)
and new incidents keep arriving while people page through it. Offset pagination
(`?page=3`) re-numbers rows on every insert: readers see duplicates or silently miss
rows, and deep offsets get slower because the database still walks the skipped rows.

## Decision

- `GET /incidents` returns `{items, next_cursor, total}`; clients pass `cursor` back.
- The cursor is opaque (base64url JSON) and holds the sort field names plus the last row's
  values for them. `id` is always appended as a unique tie-breaker, so the order is total.
- The "after" predicate is generated for any mix of directions:
  `(k1 > v1) OR (k1 = v1 AND k2 > v2) OR ...`, with `<` for descending keys.
- Only NOT NULL columns are sortable (created_at, updated_at, resolution_due_at, priority,
  status, number) plus `relevance` for searches; relevance is computed as float8 so its
  value round-trips through JSON exactly.
- A cursor that does not match the requested sort is a 422 (`invalid_cursor`).

## Consequences

- Stable pages under concurrent inserts (tested), constant cost per page with the
  composite index `(status, priority, created_at DESC) WHERE NOT is_deleted`.
- No "jump to page 7"; the UI uses infinite scroll, which fits a triage list.
- `total` is a separate `COUNT(*)` with the same filters -- fine at this scale; it is the
  first thing to cache or estimate if the table grows large.
