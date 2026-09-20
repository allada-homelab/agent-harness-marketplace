---
name: fastapi-best-practices
description: Use when working with FastAPI apps — building or reviewing APIRouter route modules, Pydantic v2 request/response models, Depends() dependencies, lifespan startup/shutdown, OAuth2/JWT auth, async SQLAlchemy sessions, TestClient/httpx tests, or uvicorn deployment. Covers the FAPI- rule family (structure, models/validation, settings, dependencies, path operations, errors, security, async DB, testing, deployment). FastAPI-specific only; general Python rules live in python-best-practices.
---

# FastAPI best practices

A curated rule set for building FastAPI services. Each rule has a stable
ID and a one-line summary. Full **What / Why / How / When-not-to-apply**
entries live in `references/`.

This skill is FastAPI-specific. Language-level concerns (typing, ruff,
pytest mechanics, packaging) live in
[`python-best-practices`](../python-best-practices/SKILL.md); container
packaging lives in
[`containers-best-practices`](../containers-best-practices/SKILL.md).

## When to apply this skill

Activate when any of these are true:

- A file imports `fastapi`, `APIRouter`, `Depends`, `pydantic`, or `uvicorn`, or you're editing a FastAPI app (`main.py` with `FastAPI(...)`, `routers/`, path-operation decorators).
- The user asks about FastAPI structure, dependencies, Pydantic models for an API, lifespan/startup events, OAuth2/JWT auth, async DB sessions, or deploying FastAPI behind a proxy or in containers.
- The user references a `FAPI-` rule ID.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply to the current file.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user.

## Rules — Structure & lifecycle

See [`references/structure.md`](./references/structure.md).

- **FAPI-001** — One `APIRouter` per domain, collected in `routers/`.
- **FAPI-002** — Declare shared auth/validation dependencies on the `APIRouter`, not per route.
- **FAPI-003** — Set `prefix`/`tags` at `include_router()` for routers reused across apps.
- **FAPI-004** — Use a `lifespan` context manager for startup/shutdown; never `@app.on_event`.
- **FAPI-005** — Share startup-created resources via `app.state`, not module-level globals.
- **FAPI-006** — Version the API by URL path prefix (`/v1`), not by header.

## Rules — Models & validation

See [`references/models-validation.md`](./references/models-validation.md).

- **FAPI-010** — Configure Pydantic v2 models with `model_config = ConfigDict(...)`, not inner `class Config`.
- **FAPI-011** — Use separate input and output models so secrets never leak into responses.
- **FAPI-012** — Prefer a return-type annotation over `response_model=` when the shapes match.
- **FAPI-013** — Set `response_model_exclude_unset=True` for sparse/partial-record responses.
- **FAPI-014** — Pair `response_class=` with `response_model=None` when returning a `Response` directly.

## Rules — Settings

See [`references/settings.md`](./references/settings.md).

- **FAPI-020** — Use `pydantic-settings` `BaseSettings` for config, not scattered `os.getenv`.
- **FAPI-021** — Wrap `Settings()` in `@lru_cache` and inject it via `Depends`.
- **FAPI-022** — Type secret fields as `SecretStr`.

## Rules — Dependencies

See [`references/dependencies.md`](./references/dependencies.md).

- **FAPI-030** — Declare dependencies as `Annotated[T, Depends(fn)]` and reuse via type aliases.
- **FAPI-031** — Wrap `yield` dependencies in `try/finally` so cleanup runs on error.
- **FAPI-032** — Use `Security(fn, scopes=[...])` (not `Depends`) for OAuth2 scope-bearing auth.

## Rules — Path operations

See [`references/path-operations.md`](./references/path-operations.md).

- **FAPI-040** — Use `async def` for I/O-bound routes; reserve `def` for sync/CPU-bound work.
- **FAPI-041** — Use `status.HTTP_*` constants and semantic codes (`201` create, `204` delete).
- **FAPI-042** — Use cursor (keyset) pagination for large collections; offset only for small bounded sets.
- **FAPI-043** — Use `BackgroundTasks` only for fire-and-forget work; escalate durable jobs to a queue.

## Rules — Error handling

See [`references/errors.md`](./references/errors.md).

- **FAPI-050** — Register handlers against `StarletteHTTPException` to also catch routing 404/405.
- **FAPI-051** — Override `RequestValidationError` to stabilize the 422 response shape.
- **FAPI-052** — Register a catch-all `Exception` handler that logs and returns a safe `500`.
- **FAPI-053** — Use a structured `detail` (dict with a code) for machine-readable errors.

## Rules — Security

See [`references/security.md`](./references/security.md).

- **FAPI-060** — Hash passwords with Argon2 via `pwdlib`; never plaintext, MD5, or SHA-1.
- **FAPI-061** — Verify against a dummy hash when the user lookup misses (timing attack).
- **FAPI-062** — Never put secrets, PII, or session state in a JWT payload.
- **FAPI-063** — Point `OAuth2PasswordBearer(tokenUrl=...)` at the real token endpoint path.

## Rules — Async database

See [`references/async-db.md`](./references/async-db.md).

- **FAPI-070** — Never use a sync SQLAlchemy `Session` inside an `async def` route.
- **FAPI-071** — Create one async engine per process, in `lifespan` — not per request.
- **FAPI-072** — Manage schema with Alembic; don't call `create_all()` in production.

## Rules — Testing

See [`references/testing.md`](./references/testing.md).

- **FAPI-080** — Use `TestClient` for sync tests, `httpx.AsyncClient` + `ASGITransport` for async.
- **FAPI-081** — Swap dependencies with `app.dependency_overrides`, not monkeypatching.
- **FAPI-082** — Enter `TestClient(app)` as a context manager so `lifespan` runs in tests.

## Rules — Deployment

See [`references/deployment.md`](./references/deployment.md).

- **FAPI-090** — Run one Uvicorn process per container; let the orchestrator replicate.
- **FAPI-091** — Set `--forwarded-allow-ips` and `root_path` when running behind a proxy.
- **FAPI-092** — Never combine `allow_origins=["*"]` with `allow_credentials=True` in CORS.
