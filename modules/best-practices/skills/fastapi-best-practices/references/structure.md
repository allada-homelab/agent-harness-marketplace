# FAPI structure & lifecycle rules

Detailed entries for `FAPI-001..FAPI-006`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI docs](https://fastapi.tiangolo.com/) — primarily
[Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
and [Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).

---

## FAPI-001 — One `APIRouter` per domain, collected in `routers/`

**What.** Each domain (users, items, orders) gets its own
`routers/<domain>.py` exposing a module-level
`router = APIRouter(prefix="/<domain>", tags=["<domain>"])`. `app/main.py`
only constructs the `FastAPI()` app and calls `app.include_router(...)`.

**Why.** A monolithic `main.py` holding hundreds of path operations
becomes unsearchable and turns every feature branch into a merge
conflict on one file. An `APIRouter` is functionally equivalent to the
full app for path operations — there is no runtime cost to splitting, so
the only thing a flat layout buys you is the merge pain.

**How.**

```python
# app/routers/users.py
from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/{user_id}")
async def get_user(user_id: int) -> UserOut:
    ...

# app/main.py
from fastapi import FastAPI
from app.routers import users, items

app = FastAPI()
app.include_router(users.router)
app.include_router(items.router)
```

**When NOT to apply.** A genuinely tiny service (a handful of routes, one
author) can keep everything in `main.py` — the split earns its keep once
there are multiple domains or contributors. Don't pre-split a 20-line
app into ten files.

---

## FAPI-002 — Declare shared auth/validation dependencies on the `APIRouter`, not per route

**What.** Dependencies common to every route in a router — auth gates,
tenant resolution, shared header validation — belong in
`APIRouter(dependencies=[Depends(verify_token)])`, not repeated in each
`@router.get(...)` decorator.

**Why.** Per-route repetition is exhaustive only by vigilance: the day
someone adds a route and forgets the `dependencies=[...]` line, that
route is a silent authorization hole. Declaring the dependency on the
router is exhaustive *by construction* — new routes inherit it
automatically, and the gap can't be introduced by omission.

**How.**

```python
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_superuser)],
)

@router.get("/stats")          # inherits the superuser gate
async def stats() -> Stats: ...
```

Per-route dependencies still stack on top when a single route needs
more.

**When NOT to apply.** When only *some* routes in the router share the
dependency — putting it on the router would over-apply it. Group those
routes into their own sub-router, or attach the dependency per route.

---

## FAPI-003 — Set `prefix`/`tags` at `include_router()` for routers reused across apps

**What.** When a router is included in more than one app (an internal SDK
router mounted by two services at different URLs), pass `prefix=`, `tags=`,
and shared `dependencies=` to `app.include_router()` rather than baking
them into the `APIRouter(...)` constructor.

**Why.** A hardcoded `prefix="/users"` in the constructor makes the
router non-reusable at a different mount point. The `include_router`
parameters extend the router's own values, so leaving them off the
constructor keeps the router environment-agnostic and lets each host app
decide where it lives.

**How.**

```python
# shared library: routers/admin.py
router = APIRouter()            # no prefix/tags baked in

# service A
app.include_router(admin.router, prefix="/internal/admin", tags=["admin"])
# service B
app.include_router(admin.router, prefix="/v2/admin", tags=["admin"])
```

**When NOT to apply.** A router used by exactly one app — keep `prefix`
and `tags` on the constructor (FAPI-001), it reads better co-located with
the routes.

---

## FAPI-004 — Use a `lifespan` context manager for startup/shutdown; never `@app.on_event`

**What.** All startup and shutdown logic (DB pool init, model loading,
cache warming) lives in a single `@asynccontextmanager` `lifespan`
function passed to `FastAPI(lifespan=lifespan)`. Code before `yield` runs
at startup; code after runs at shutdown.

**Why.** `@app.on_event("startup")` / `@app.on_event("shutdown")` are
deprecated, and — the real footgun — they are **silently ignored** when a
`lifespan=` is also provided. A codebase that mixes the two drops the
event handlers with no error. `lifespan` also keeps paired setup/teardown
co-located, removing the globals you'd otherwise need to pass a pool from
startup to shutdown.

**How.**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await create_pool(settings.db_url)
    app.state.pool = pool
    try:
        yield
    finally:
        await pool.close()

app = FastAPI(lifespan=lifespan)
```

**When NOT to apply.** Never for new code. Existing `@app.on_event`
handlers are the one case where it's already wired — migrate them, and do
it *before* introducing a `lifespan` (or the events will vanish).

---

## FAPI-005 — Share startup-created resources via `app.state`, not module-level globals

**What.** Resources created in `lifespan` (connection pools, loaded
models, HTTP clients) attach to `app.state` (`app.state.pool = pool`) and
are read in routes via `request.app.state.pool`.

**Why.** Module-level globals defeat test isolation (every test must
remember to reset them) and are per-process — with multiple workers each
holds its own copy, so anything you mutate as "shared state" silently
diverges across workers. `app.state` is scoped to the application
instance, which makes the lifetime explicit and lets tests mount a
configured app.

**How.**

```python
# in lifespan
app.state.redis = await create_redis_pool(settings.redis_url)

# in a route
from fastapi import Request

@router.get("/cached")
async def cached(request: Request):
    redis = request.app.state.redis
    ...
```

Prefer a dependency that reads from `app.state` so routes don't all take
a bare `Request` (`async def get_redis(request: Request): return request.app.state.redis`).

**When NOT to apply.** Truly process-global, immutable constants
(compiled regexes, static lookup tables) are fine as module globals —
`app.state` is for per-app *resources* with a lifecycle, not for
constants.

---

## FAPI-006 — Version the API by URL path prefix (`/v1`), not by header

**What.** Expose versions as `app.include_router(v1, prefix="/v1")` /
`app.include_router(v2, prefix="/v2")`. Avoid header-based versioning
(`Accept-Version: 2`) in FastAPI-generated APIs.

**Why.** Header versioning is invisible in access logs, not cacheable
per-version by a CDN, unrepresentable in the OpenAPI `paths` object, and
untestable from a browser address bar. Path versioning yields a clean
OpenAPI schema where each version is a distinct path group, and generated
clients can target a version by URL.

**How.**

```python
app.include_router(v1_router, prefix="/v1", tags=["v1"])
app.include_router(v2_router, prefix="/v2", tags=["v2"])
```

**When NOT to apply.** APIs with a strict hypermedia/content-negotiation
contract that already standardizes on media-type versioning
(`Accept: application/vnd.api.v2+json`), or a single-consumer internal
API where you roll forward in place and never run two versions at once.
