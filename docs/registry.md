# Living Bug Registry

Scans are events. The registry is the product's memory.

## Identity

A canonical issue is keyed by:

- project
- detection category
- normalized route (path only, no query or fragment)
- DOM fingerprint (or selector)
- normalized error signature (numbers collapsed)

Titles and descriptions are deliberately excluded so copy changes do not create duplicates. A fuzzy
fallback merges only on strong signals: the same fingerprint, the same normalized signature on the
same route, or the same selector with a very similar title. Different fingerprints never merge,
because showing a duplicate is better than hiding a distinct bug.

## Occurrences

Every scan that observes the issue adds an `issue_occurrences` row:

- scan id, finding id, URL, route, viewport
- severity, priority, confidence at that time
- whether it was reproduced
- a snapshot of the evidence kinds

The canonical record keeps counters (`occurrence_count`, `affected_scan_count`) and first/last seen
timestamps, but historical evidence is never overwritten.

## Lifecycle

```
new → triaged → confirmed → in_progress → fixed → verified → closed
        ↘ needs_review ↗        ↘ blocked ↗
new/triaged/confirmed → false_positive | duplicate
closed/fixed/verified → reopened
```

Transitions are validated in `bugpilot_core.registry.can_transition`. An invalid transition returns
`409 invalid_transition` with the allowed targets, and every transition is written to `issue_events`
with author, from, to and note.

## Regressions

If an issue is `fixed`, `verified` or `closed` and is detected again:

- status becomes `reopened`
- `is_regression = true`
- `reopened_count` increments
- a `regression` event is recorded
- priority is recalculated with the regression boost

## Priority rationale

Priority is explainable. The issue and the finding both expose `priority_rationale`, for example:

```
severity medium contributes 0.34
confirmed by evidence (+0.20)
route is marked business-critical (+0.15)
total 0.69 → P1
```

Severity answers "how bad", priority answers "how soon", confidence answers "how sure". They are
stored and displayed separately and are never treated as interchangeable.

## Searching and viewing

`GET /api/v1/issues` filters in SQL so `total` and pagination are always correct:

- project, severity, priority, status, confidence, category, route, owner
- `scan_id` (issues seen in one scan), `regression`, `recurring`
- first/last seen date ranges, free-text search over title, summary, route and selector
- sorting: last seen, first seen, severity, priority, occurrence count, status, title
- grouping by severity, priority, status, category, project or owner, with counts over the
  whole filtered set rather than just the current page

`GET /api/v1/issues/trends?days=14` returns new, resolved and reopened counts per day.

## Bulk triage

`POST /api/v1/issues/bulk` applies one action to up to 200 issues:

```json
{"issue_ids": ["..."], "action": "transition", "status": "triaged", "author": "qa"}
```

Each issue is validated independently, so an invalid transition is reported per issue instead of
discarding the rest of the batch. The response separates `updated` from `failed` with reasons.

## Duplicate suggestions

`GET /api/v1/issues/{id}/duplicates` ranks plausible duplicates. It requires a strong signal (same
DOM fingerprint, same normalized error signature, same selector, or a very similar title) in
addition to a score threshold, because the same category on the same route is a coincidence, not a
duplicate. Merging is always confirmed by a human; the merged issue keeps both histories.

## Manual control

- `PATCH /issues/{id}` edits documentation fields.
- `POST /issues/{id}/transition` moves status with validation.
- `POST /issues/{id}/notes` adds an audit note.
- `POST /issues/{id}/assign` sets an owner and records the change.
- `POST /issues/{id}/merge` folds a duplicate into a canonical issue while keeping occurrences.

## Fix verification

See [verification.md](verification.md). In short: `POST /issues/{id}/verify-fix` replays the
recorded actions, re-runs the detector and returns `fixed`, `still_failing` or `inconclusive`.
Only a completed replay with no matching signal is `fixed`; anything ambiguous is
`inconclusive` and the issue moves to `needs_review`.

## Reporting

Reports are generated from the registry, not from example data. Each issue record includes the
summary, technical explanation, expected/observed behaviour, reproduction steps, root-cause
hypothesis with its confirmation status, suggested fix, evidence and occurrence history. Root causes
are labelled `unconfirmed` unless a human changes them.