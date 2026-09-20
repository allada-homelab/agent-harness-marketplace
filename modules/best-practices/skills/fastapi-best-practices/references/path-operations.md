# FAPI path-operation rules

Detailed entries for `FAPI-040..FAPI-043`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI async docs](https://fastapi.tiangolo.com/async/),
[response status code](https://fastapi.tiangolo.com/tutorial/response-status-code/),
and [background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/).

---

## FAPI-040 — Use `async def` for I/O-bound routes; reserve `def` for sync/CPU-bound work

**What.** Declare a handler `async def` when it `await`s I/O (async DB
driver, `httpx`, async cache). Use plain `def` only when the body is a
synchronous library call or CPU-bound work — FastAPI runs `def` handlers
in a thread pool so they don't block the loop.

**Why.** The dangerous combination is a blocking call *inside* `async
def`: `requests.get(url)` or a sync `Session.execute()` in an `async def`
route freezes the entire event loop for the duration of that call, so
every other in-flight request stalls. FastAPI can't detect it; the app
just silently collapses under concurrency. (See FAPI-070 for the
sync-DB-in-async case specifically.) Counterintuitively, a sync handler
written as `def` is *safer* than an `async def` that hides a blocking
call, because the thread pool absorbs it.

**How.**

```python
# I/O-bound → async, with async clients
@router.get("/users/{uid}")
async def get_user(uid: int) -> UserOut:
    return await repo.get(uid)            # async DB

# sync-only library or CPU work → def (runs in the thread pool)
@router.post("/thumbnail")
def make_thumbnail(image: bytes) -> bytes:
    return pillow_resize(image)           # blocking, but off the loop

# one-off blocking call from inside async:
from starlette.concurrency import run_in_threadpool
result = await run_in_threadpool(blocking_fn, arg)
```

**When NOT to apply.** Never — the principle (don't block the event
loop) is absolute. The only judgment is per-handler: choose `async def`
vs `def` by what the body actually does, not by a blanket rule. A handler doing only fast in-memory
work can be either; it won't matter.

---

## FAPI-041 — Use `status.HTTP_*` constants and semantic codes (`201` create, `204` delete)

**What.** Declare non-200 status codes with `from fastapi import status`
constants, and use the semantically correct code: `201 Created` for
resource creation, `204 No Content` for deletes that return no body — not
a default `200`.

**Why.** Two problems with raw integers and wrong codes. Raw literals
(`status_code=201`) are typo-prone and unreadable. Wrong semantics break
contracts: a generated SDK client uses the status code to decide whether
to parse a body, so a `204` that returns content or a `200` that created a
resource confuses clients and violates REST expectations.

**How.**

```python
from fastapi import status

@router.post("/users/", status_code=status.HTTP_201_CREATED)
async def create_user(user: UserIn) -> UserOut: ...

@router.delete("/users/{uid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(uid: int) -> None: ...
```

**When NOT to apply.** A plain `200` read endpoint needs no
`status_code=` at all — the rule is about *non-200* codes and getting
creation/deletion semantics right, not annotating every route.

---

## FAPI-042 — Use cursor (keyset) pagination for large collections; offset only for small bounded sets

**What.** For any collection that can grow past a few thousand rows,
return an opaque `next_cursor` the client echoes back to fetch the next
page. Reserve `skip`/`limit` (offset) pagination for small, bounded,
admin-facing lists.

**Why.** SQL `OFFSET N` scans and discards N rows before returning the
page — at offset 100,000 that's effectively a table scan on every
request, and it gets slower the deeper you page. Keyset pagination
(`WHERE id > :last_seen ORDER BY id LIMIT :n`) is O(page size) regardless
of depth given an index, and it's stable under concurrent inserts (offset
pagination skips or repeats rows when the underlying set shifts).

**How.**

```python
@router.get("/events")
async def list_events(
    limit: int = 50,
    cursor: str | None = None,
) -> Page[Event]:
    after = decode_cursor(cursor) if cursor else None
    rows = await repo.page_after(after, limit)          # WHERE id > after ...
    return Page(items=rows, next_cursor=encode_cursor(rows[-1].id) if rows else None)
```

Encode (and ideally sign) the cursor; don't expose a raw primary key.

**When NOT to apply.** Small, fixed datasets where users genuinely need
to jump to "page 7" (an admin table of a few hundred rows). Offset
pagination is simpler and fine there — the cost only bites at scale and
depth.

---

## FAPI-043 — Use `BackgroundTasks` only for fire-and-forget work; escalate durable jobs to a queue

**What.** `BackgroundTasks.add_task(...)` fits short, non-critical,
post-response work: sending one notification email, writing an audit
entry, bumping a counter. It is not for anything needing retries,
persistence, progress, or more than a second or two of work.

**Why.** Background tasks run in the same process as the web server —
there is no retry, no persistence, and the task dies with the worker. An
email that fails because SMTP blipped is simply lost; a "background"
report that takes 30s ties up the worker and still vanishes on a deploy
restart. Durable work needs a real queue (ARQ for async-native, Celery/RQ
otherwise) with its own broker and retry semantics.

**How.**

```python
@router.post("/signup")
async def signup(data: SignupIn, bg: BackgroundTasks) -> UserOut:
    user = await create_user(data)
    bg.add_task(send_welcome_email, user.email)   # fire-and-forget, OK to lose
    return user
```

**When NOT to apply.** The rule is the boundary itself — anything
retryable, long-running, or that must survive a restart crosses it and
belongs in a task queue, not `BackgroundTasks`.
