# Architecture

## Request and scan lifecycle

```mermaid
sequenceDiagram
  participant U as User
  participant E as Extension / Dashboard
  participant A as API
  participant Q as Redis queue
  participant W as Worker
  participant P as Playwright
  participant R as Registry

  U->>E: Choose scope and start
  E->>A: POST /scans (scope, budgets, idempotency key)
  A->>A: Validate target, clamp budgets, persist scope
  A->>Q: enqueue scan
  Q->>W: dequeue and claim (conditional update)
  W->>W: build scope guard from scan_json
  W->>P: navigate, snapshot, act
  W->>W: run detectors, dedupe, score
  W->>R: record occurrence per finding
  W-->>A: publish events (Redis or scan_events table)
  E->>A: poll / subscribe to events
  A-->>E: progress, findings, counts
  U->>A: open registry, transition issue, export report
```

## Modules

| Module | Responsibility |
| --- | --- |
| `bugpilot_core/models.py` | Pydantic contracts: scope, config, findings, events, enums |
| `bugpilot_core/scope.py` | Hard scope enforcement: navigation, actions, depth, patterns |
| `bugpilot_core/agent/graph.py` | LangGraph workflow and node implementations |
| `bugpilot_core/agent/browser.py` | Playwright session, DOM snapshot, screenshots, console/network capture |
| `bugpilot_core/detectors/` | Deterministic checks; no AI required |
| `bugpilot_core/ai/` | Provider interface, Gemini, OpenAI, deterministic local fallback |
| `bugpilot_core/dedupe.py` | Semantic overlap within a scan |
| `bugpilot_core/severity.py` | Severity scoring and explainable priority scoring |
| `bugpilot_core/registry.py` | Canonical issues, occurrences, lifecycle, merge, regression |
| `bugpilot_core/evidence.py` | Storage adapter, redaction, signed URLs, retention |
| `bugpilot_core/reporting.py` | Markdown, PDF and ZIP exports |
| `bugpilot_core/events.py` | Redis pub/sub with durable database fallback |

## The agent graph

```
START → initialize → analyze_page → discover_elements → run_detectors
      → analyze_suspicious (only if signals) → collect_evidence
      → verify_findings → update_state
            ├─ plan_action → execute_action → observe → run_detectors (loop)
            └─ generate_report → END
```

Budgets are checked in `update_state`: duration, pages, actions, model calls, and "no new states".
Pause and stop are read from the database on every action, so they work while the agent is running,
even from another process.

Verification re-snapshots the page and re-runs the detectors. This is honest but limited: it proves
the signal still exists at that moment, not that a specific user flow reproduces it. The UI and
reports label confidence accordingly.

## Scope enforcement

`ScanScope` is stored in `test_sessions.scope_json` and reconstructed into a `ScopeGuard` by the
worker. Every planned action is checked twice: when planning and immediately before execution.
Navigation is re-validated after a click, because form submits and scripts can navigate without an
`href`. Anything that escapes the scope is rolled back and recorded in `actions.block_reason` and
`test_sessions.pages_skipped`.

## Data model

```mermaid
erDiagram
  projects ||--o{ test_sessions : has
  projects ||--o{ issues : owns
  test_sessions ||--o{ pages : records
  test_sessions ||--o{ actions : records
  test_sessions ||--o{ findings : produces
  findings ||--o{ finding_evidence : captures
  findings ||--o{ verification_runs : verifies
  issues ||--o{ findings : canonicalises
  issues ||--o{ issue_occurrences : occurs
  issues ||--o{ issue_events : audits
  issues ||--o{ issue_evidence : stores
  test_sessions ||--o{ scan_events : streams
```

Migrations live in `migrations/` and are applied on startup by `init_db()`. Create a new revision
with:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

## Event transport

- With Redis: events are published to `bugpilot:scan:<id>` and appended to a capped list.
- Without Redis: events are stored in `scan_events`, and the WebSocket polls durable history. This
  keeps the API and worker consistent locally without hiding the missing dependency.

`GET /api/v1/health` reports which transport is active.

## AI usage

AI is used for visual anomaly hypotheses and reasoning (expected vs observed, root cause, suggested
fix, reproduction steps). Deterministic tools own browser actions, scope and verification. Model
calls are capped per scan and logged in `model_runs` with latency and provider.