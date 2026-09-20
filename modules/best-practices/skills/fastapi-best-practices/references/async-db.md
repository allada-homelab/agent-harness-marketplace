# FAPI async-database rules

Detailed entries for `FAPI-070..FAPI-072`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI SQL databases docs](https://fastapi.tiangolo.com/tutorial/sql-databases/),
[SQLAlchemy asyncio docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html),
and [Alembic docs](https://alembic.sqlalchemy.org/).

---

## FAPI-070 — Never use a sync SQLAlchemy `Session` inside an `async def` route

**What.** An `async def` handler must not call a synchronous
`sqlalchemy.orm.Session` (`session.execute(...)` on a sync session). Use
`AsyncSession` from `sqlalchemy.ext.asyncio` with an async driver
(`postgresql+asyncpg://`), or make the handler a `def` so FastAPI runs it
in the thread pool.

**Why.** A sync DB call inside `async def` blocks the event loop for the
whole round-trip — every other concurrent request stalls behind it. It's
the single most common FastAPI performance bug, and it's silent: a
single-request test passes fine and the app only falls over under
concurrent load. (This is the DB-specific case of FAPI-040.)

**How.**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

engine = create_async_engine("postgresql+asyncpg://...")

async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine) as session:
        yield session

@router.get("/items/{item_id}")
async def get_item(item_id: int, db: Annotated[AsyncSession, Depends(get_db)]) -> ItemOut:
    return await db.get(Item, item_id)
```

For a legacy sync-only data layer, wrap the call:
`await run_in_threadpool(sync_query, ...)`.

**When NOT to apply.** A fully synchronous app where every route is `def`
(FastAPI threads them) is internally consistent and fine — the rule is
specifically against *mixing* a sync session into an `async def` route.

---

## FAPI-071 — Create one async engine per process, in `lifespan` — not per request

**What.** `create_async_engine(...)` owns a connection pool. Create it
once at startup (in `lifespan`, stored on `app.state`) and share it.
Never call `create_async_engine` inside the per-request session
dependency.

**Why.** Creating an engine per request throws away and rebuilds the pool
every time, so each request opens a fresh TCP (and TLS) connection to the
database — adding latency and, under load, exhausting the database's
connection limit. The pool only helps if it lives for the process.

**How.**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = create_async_engine(settings.db_url, pool_size=20)
    try:
        yield
    finally:
        await app.state.engine.dispose()

async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(request.app.state.engine) as session:
        yield session
```

**When NOT to apply.** Tests sometimes build a throwaway engine per test
module against a temp database — that's a deliberate isolation choice, not
the per-*request* anti-pattern this rule targets.

---

## FAPI-072 — Manage schema with Alembic; don't call `create_all()` in production

**What.** `Base.metadata.create_all()` is fine for a SQLite demo or a
quickstart. Production schema changes go through Alembic migration
scripts run before the app starts.

**Why.** `create_all()` is purely additive — it creates missing tables
but never alters or drops existing columns. A renamed or retyped column
silently coexists with the old one, so a breaking schema change that
should block the deploy is instead skipped, leaving the app running
against an inconsistent schema. Alembic makes each change an explicit,
reviewable, ordered migration.

**How.**

```bash
alembic init alembic
alembic revision --autogenerate -m "add users.last_login"
alembic upgrade head        # run in CI/CD before starting the app
```

Run migrations as a **single** pre-deploy step — not from `lifespan`, and
not once per replica. With multiple pods (FAPI-090), N replicas each
running `upgrade head` on startup race each other; a dedicated job (a
Kubernetes `Job` or init container) applies them exactly once. Remove any
`create_all()` from `lifespan` once Alembic is wired.

**When NOT to apply.** Throwaway prototypes, SQLite-backed demos, and
test fixtures where the schema is recreated from scratch each run —
`create_all()` is the simpler choice there.
