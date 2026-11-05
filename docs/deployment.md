# Deployment

## Local Docker Compose

```bash
export EVIDENCE_SIGNING_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))")
export GEMINI_API_KEY=...        # optional
docker compose up --build
```

Services:

| Service | Port | Notes |
| --- | --- | --- |
| web | 3000 | Production Next.js build |
| api | 8000 | Runs Alembic migrations on startup |
| worker | — | Playwright image with Chromium |
| postgres | 5432 | Persistent volume |
| redis | 6379 | Queue + pub/sub |
| fixture | 4173 | The deliberately broken demo shop |

The demo flow: open <http://localhost:3000>, scan `http://127.0.0.1:4173/` (inside the worker
container the fixture is reachable as `http://fixture:4173/`), then open the registry and export a
report.

## Required production settings

| Variable | Why |
| --- | --- |
| `BUGPILOT_ENV=production` | Enables strict target validation |
| `DATABASE_URL` | PostgreSQL with `asyncpg` |
| `REDIS_URL` | Cross-process events and queue |
| `EVIDENCE_SIGNING_SECRET` | Evidence URLs are signed; the API refuses to boot without it |
| `EVIDENCE_DIR` | Mounted volume, or `EVIDENCE_STORAGE=s3` once implemented |
| `WEB_ORIGIN` / `CORS_ORIGINS` | Restrict browser origins |
| `BLOCK_PRIVATE_TARGETS=true` | SSRF defence |
| `ALLOWED_HOST_SUFFIXES` | Restrict scannable domains |

## Migrations

Migrations are applied automatically by `init_db()` on API and worker startup. To run them
explicitly (for example in a release step):

```bash
alembic upgrade head
alembic current
alembic downgrade -1
```

Generate a new revision after changing `packages/core/bugpilot_core/db/models.py`:

```bash
alembic revision --autogenerate -m "add x"
```

Review the generated file before committing: autogenerate does not infer data migrations.

## Health and shutdown

- `GET /health` — liveness.
- `GET /api/v1/health` — includes the active event transport.
- The worker claims scans with a conditional update, so scaling to multiple workers does not run the
  same scan twice.
- SIGINT/SIGTERM set a shutdown flag; the worker finishes the current scan before exiting.
- Docker health checks are defined for the API and its dependencies.

## Evidence storage

Development uses local disk. Production should use object storage; the `s3` adapter currently fails
closed until credentials are implemented, which is intentional: silently writing evidence to a
container filesystem would lose it on redeploy.

Retention: set `evidence_retention_days` per project. `EvidenceStore.purge_older_than` is available
for a scheduled cleanup job; no scheduler is bundled.

## Scaling notes

- The API is stateless; scale horizontally behind a load balancer.
- Workers are CPU-heavy and browser-bound; scale by adding worker containers, not threads.
- PostgreSQL is the source of truth; Redis is required for live events across processes.
- Keep `MAX_*_HARD_LIMIT` values conservative until you have measured real scan cost.

## Not included

Authentication, multi-tenancy, rate limiting, a scheduler for retention and GitHub integration are
out of scope for this iteration and are listed in [limitations.md](limitations.md).