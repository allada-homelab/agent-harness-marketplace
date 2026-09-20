# PY async rules

Detailed entries for `PY-040..PY-049` plus newer cross-cutting
async rules (`PY-067`, `PY-068`, `PY-079`). Each follows the
four-part **What / Why / How / When NOT to apply** shape.

Citations point at the
[asyncio docs](https://docs.python.org/3/library/asyncio.html),
[asyncio-dev docs](https://docs.python.org/3/library/asyncio-dev.html),
[anyio docs](https://anyio.readthedocs.io/),
[PEP 525 — async generators](https://peps.python.org/pep-0525/),
[PEP 703 / PEP 779 — free-threaded Python](https://peps.python.org/pep-0779/),
and [CPython issue #117379](https://github.com/python/cpython/issues/117379)
(GC of unreferenced tasks).

---

## PY-040 — `asyncio` for I/O-bound concurrency only

**What.** Use `asyncio` (or anyio) for I/O-bound work: network
calls, disk I/O, subprocess waits, anything that blocks on
*external* state. CPU-bound work belongs in `ProcessPoolExecutor`,
not coroutines. (On Python 3.14+, `concurrent.interpreters.InterpreterPoolExecutor`
is a lighter alternative for pure-Python CPU-bound work — see PY-083.)

**Why.** asyncio achieves concurrency by yielding control at
`await` points. A coroutine that *doesn't yield* — because it's
doing CPU work in a tight loop — blocks the entire event loop.
Every other task starves until that one coroutine returns.

Concrete failure: an async HTTP server with one handler that does
`json.loads(50_MB_payload)`. The `loads()` call takes 800ms; for
those 800ms, no other request is processed, no timeout fires, no
healthcheck responds. Server appears hung. Same for any heavy
computation: tokenization, image processing, numpy math.

The runtime gives no warning. The handler just runs and the event
loop stalls.

**How.**

```python
import asyncio
from concurrent.futures import ProcessPoolExecutor

executor = ProcessPoolExecutor(max_workers=4)

async def handle_upload(data: bytes) -> dict:
    # I/O — fine in async
    await save_to_blob_storage(data)

    # CPU — offload to a worker process
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, process_image, data)

    return result
```

For threads (not processes — for I/O-bound C extensions that release the GIL):

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

thread_pool = ThreadPoolExecutor(max_workers=8)

async def query_legacy_db(sql: str):
    loop = asyncio.get_running_loop()
    # legacy_driver.execute is sync but releases the GIL in its C extension
    return await loop.run_in_executor(thread_pool, legacy_driver.execute, sql)
```

asyncio's `asyncio.to_thread()` (3.9+) is a shortcut for the thread
case:

```python
result = await asyncio.to_thread(blocking_function, arg1, arg2)
```

**When NOT to apply.** Lightweight CPU work (<10ms) is fine inline
— the cost of marshalling to another process is higher than the
work itself. Use `run_in_executor` when the work is genuinely long.

---

## PY-041 — Never call blocking I/O inside async; use debug mode

**What.** Blocking calls that *don't* yield control are forbidden
inside async functions. The biggest offenders:

| Blocking | Async replacement |
|---|---|
| `requests.get(...)` | `httpx.AsyncClient.get(...)` |
| `time.sleep(n)` | `asyncio.sleep(n)` |
| `open(...).read()` | `aiofiles.open(...)` (or `asyncio.to_thread`) |
| `subprocess.run(...)` | `asyncio.create_subprocess_exec(...)` |
| `psycopg2` (sync) | `asyncpg` or `psycopg[async]` |
| `redis.Redis` | `redis.asyncio.Redis` |
| `boto3` | `aioboto3` (or `asyncio.to_thread` for occasional calls) |

Enable asyncio debug mode during development to detect violations:

```python
asyncio.run(main(), debug=True)
```

or set the env var:

```bash
PYTHONASYNCIODEBUG=1 python -m myapp
```

**Why.** Blocking I/O in async has the same failure mode as CPU-bound
work (PY-040): the event loop stalls. The difference is that I/O
blocking is *common* — `requests` was the standard sync HTTP library
for a decade and everyone has it in muscle memory. Mixing `requests`
into an async handler is a routine mistake.

Debug mode catches the most common cases:

- Logs warnings when a callback takes >100ms (configurable via
  `loop.slow_callback_duration`).
- Logs warnings about unawaited coroutines.
- Logs warnings about tasks destroyed before completion.
- Forces traceback objects on lost exceptions (which otherwise
  vanish silently in fire-and-forget tasks).

In production: leave debug mode off (it's heavier). In dev / CI:
turn it on.

**How.**

```python
# main.py
import asyncio
import logging
import os

logging.basicConfig(level=logging.WARNING)

async def main():
    # your app

if __name__ == "__main__":
    debug = os.getenv("ENVIRONMENT") == "development"
    asyncio.run(main(), debug=debug)
```

For tests with pytest-asyncio:

```toml
[tool.pytest.ini_options]
env = [
  "PYTHONASYNCIODEBUG=1",
]
asyncio_mode = "auto"
```

For long-running blocking operations that you don't have an async
version of, `asyncio.to_thread()` offloads them:

```python
# bad
async def handler():
    data = requests.get(URL).json()  # blocks event loop
    return data

# good — quick wrap
async def handler():
    data = await asyncio.to_thread(lambda: requests.get(URL).json())
    return data

# best — use an async library
async def handler():
    async with httpx.AsyncClient() as client:
        resp = await client.get(URL)
    return resp.json()
```

**When NOT to apply.** Two cases:

1. **Setup code at startup** that runs once before the event loop is hot — synchronous `boto3` calls to load config are fine; they don't block anything important because nothing is running yet.
2. **Sync-only libraries with no async equivalent.** Wrap in `asyncio.to_thread()`. The blocking is real but contained, and the cost is fine when the call frequency is low.

---

## PY-042 — `asyncio.run()` at the top level only

**What.** Call `asyncio.run(coro())` exactly once per program, at
the top level. Never nest `asyncio.run()` inside another async
context. Never use `nest_asyncio` outside Jupyter notebooks. And don't
reach for `asyncio.get_event_loop()` to obtain a loop — it raises
`RuntimeError` on Python 3.14+ when none is running; use
`asyncio.get_running_loop()` inside async code (see PY-084).

```python
# RIGHT
async def main():
    result = await fetch_data()
    print(result)

if __name__ == "__main__":
    asyncio.run(main())

# WRONG — nested run
async def some_handler():
    other_result = asyncio.run(other_async_fn())  # RuntimeError: This event loop is already running
```

**Why.** `asyncio.run()` creates a new event loop and blocks the
calling thread until the coroutine finishes. Calling it when a loop
is already running raises `RuntimeError: This event loop is already
running`.

The `nest_asyncio` antipattern: monkey-patches asyncio internals
globally to allow nesting. It exists for one legitimate reason —
Jupyter notebooks, which run their own event loop and need a way for
user cells to call `asyncio.run`. Outside notebooks, it's almost
always covering up an architectural problem ("we have an async
library but I want to call it from sync code at one specific
place"). The right fix is usually to make the calling code async too,
or to use `asyncio.run` at a higher level.

A separate but related deprecation: `asyncio.get_event_loop()` is
deprecated when there's no running loop and will be removed. Use:

- `asyncio.get_running_loop()` inside async functions (errors if no loop)
- `asyncio.run(main())` to start the loop from sync code

**How.**

```python
# Standard pattern
import asyncio

async def main():
    async with AsyncContext() as ctx:
        await do_stuff(ctx)

if __name__ == "__main__":
    asyncio.run(main())
```

For a sync entry point that needs to call async code:

```python
# RIGHT
def sync_entry():
    return asyncio.run(async_helper())

async def async_helper():
    ...

# WRONG
def sync_entry():
    loop = asyncio.get_event_loop()        # deprecated
    return loop.run_until_complete(async_helper())
```

To run a *new* loop in a thread (rare, but legitimate when bridging
sync and async code via threads):

```python
def thread_target():
    asyncio.run(async_function())     # OK — each thread has its own loop

thread = threading.Thread(target=thread_target)
thread.start()
```

**When NOT to apply.** Jupyter notebooks legitimately use
`nest_asyncio` to support `await` in cells. That's the only context
where it's defensible.

---

## PY-043 — `TaskGroup` over `gather`; re-raise `CancelledError`

**What.** Two related rules:

1. **For running concurrent tasks, prefer `asyncio.TaskGroup`
   (Python 3.11+) over `asyncio.gather()`.** TaskGroup provides
   structured concurrency: any task failure cancels the others and
   raises an `ExceptionGroup` containing all failures.
2. **When you catch `CancelledError`, always re-raise it** after
   doing cleanup. Suppressing it breaks TaskGroup's cancellation
   propagation.

```python
# RIGHT — TaskGroup (3.11+)
async def fetch_all():
    async with asyncio.TaskGroup() as tg:
        task1 = tg.create_task(fetch(url1))
        task2 = tg.create_task(fetch(url2))
    # Both tasks done here; any exception is re-raised as ExceptionGroup

# RIGHT — cancellation cleanup
async def worker():
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await cleanup()
        raise        # critical — propagate cancellation
```

**Why.** Two failure modes:

1. **`gather` lets failures slip through silently.** By default,
   `asyncio.gather(*tasks)` continues running the remaining tasks
   when one raises — and only raises *one* exception at the end. The
   others are lost. With `return_exceptions=True`, exceptions become
   values in the result list, but it's easy to forget to check them.
   TaskGroup raises an `ExceptionGroup` with *all* failures, and
   automatically cancels in-flight siblings on the first failure
   (structured cancellation).
2. **Suppressing `CancelledError` breaks the parent.** When a
   TaskGroup task is cancelled (because a sibling failed), it
   receives `CancelledError`. If your code catches it and doesn't
   re-raise, the task appears to have completed normally — TaskGroup
   thinks all is well. Then the *parent's* `__aexit__` raises the
   sibling's exception, but the task that was supposed to clean up
   never did, and there's no signal of what went wrong.

The rule: catch `CancelledError` only to release resources, then
`raise` to continue propagation.

**How.**

```python
import asyncio

# TaskGroup with structured concurrency
async def fetch_all(urls: list[str]) -> list[Response]:
    results = []
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch(url)) for url in urls]
    # After exiting the TaskGroup, all tasks are done or all are cancelled
    return [t.result() for t in tasks]

# Cancellation handling in a long-running task
async def background_worker(queue: asyncio.Queue):
    try:
        while True:
            item = await queue.get()
            try:
                await process(item)
            finally:
                queue.task_done()
    except asyncio.CancelledError:
        # Cleanup on cancellation
        await flush_pending()
        raise   # propagate; don't swallow

# gather is still right for "run everything, collect results including failures"
results = await asyncio.gather(
    fetch(url1),
    fetch(url2),
    fetch(url3),
    return_exceptions=True,   # explicit: each result is either a value or an Exception
)
for r in results:
    if isinstance(r, Exception):
        handle_failure(r)
```

**When NOT to apply.** Three cases:

1. **Python <3.11** — TaskGroup isn't available. Use `gather` with `return_exceptions=True`.
2. **You explicitly want partial-failure semantics.** Sometimes "run all 100 webhook deliveries; some will fail; that's fine" is the design. `gather(..., return_exceptions=True)` plus handling each result is the right tool.
3. **Fire-and-forget tasks that shouldn't cancel siblings.** Different shape entirely — use `asyncio.create_task()` and hold a reference to prevent GC (see the `Set[Task]` pattern in the asyncio docs).

---

## PY-044 — `contextlib.aclosing` for async generators

**What.** When you might break out of an `async for` loop early
(or otherwise abandon an async generator mid-iteration), wrap the
generator in `contextlib.aclosing()`. Don't rely on GC to call
`aclose()`.

```python
from contextlib import aclosing

async with aclosing(stream_records()) as records:
    async for record in records:
        if done(record):
            break        # generator.aclose() is called on context exit
```

**Why.** An async generator's `finally` block may hold a real
resource:

```python
async def stream_records():
    conn = await db.connect()
    try:
        async for row in conn.stream("SELECT * FROM users"):
            yield row
    finally:
        await conn.close()    # critical — but when does this run?
```

If you abandon iteration mid-stream (`break`, `return`, an exception
in the consumer), the `finally` runs *eventually* — when garbage
collection finalizes the generator. But:

1. **GC timing is non-deterministic.** Days might pass; the
   connection is held the whole time.
2. **GC happens in an unpredictable context.** When CPython's
   refcount-based GC drops the generator, it may be after the event
   loop is torn down — at which point `await conn.close()` can't
   complete because there's no loop to run it on. The cleanup never
   actually happens; the connection leaks.

`aclosing()` guarantees `aclose()` is called when the `with` block
exits, in the right async context, deterministically.

**How.**

```python
from contextlib import aclosing

# Consumer side
async def find_admin():
    async with aclosing(stream_records()) as records:
        async for record in records:
            if record["role"] == "admin":
                return record   # aclose() runs cleanly here
    return None
```

For producers, design the generator with cleanup that *must* run:

```python
async def stream_records():
    conn = await db.connect()
    try:
        async for row in conn.stream("SELECT * FROM users"):
            yield row
    finally:
        await conn.close()
```

And consumers always wrap in `aclosing()`. This is structured
cleanup analogous to context managers for sync resources.

**When NOT to apply.** Generators that complete their iteration
naturally (no `break`/`return`/exception in the consumer) — the
generator runs to exhaustion, the `finally` runs at the StopAsyncIteration,
and `aclosing()` adds no value. The rule targets the case where
early termination is possible.

---

## PY-045 — `anyio` for library code that must be runtime-agnostic

**What.** If you're writing a *library* that may be used in
applications running on either asyncio or Trio, write to `anyio`
rather than raw asyncio. anyio provides a single API that runs
unmodified on both backends.

For *application* code that owns its runtime choice — and that
choice is asyncio — use asyncio directly. The extra abstraction
isn't worth it if you're never switching backends.

```python
# Library code — anyio
import anyio

async def fetch_with_timeout(url: str) -> bytes:
    with anyio.fail_after(5.0):           # works on asyncio AND trio
        return await fetch(url)

# Application code — asyncio is fine
async def fetch_with_timeout(url: str) -> bytes:
    async with asyncio.timeout(5.0):       # asyncio-only
        return await fetch(url)
```

**Why.** Two real benefits to anyio:

1. **Runtime portability.** Trio has a meaningfully different
   programming model — structured concurrency was Trio's invention,
   later adopted by asyncio's TaskGroup. Some users prefer Trio for
   its stricter semantics. A library that only supports asyncio
   excludes them.
2. **anyio preserves context variables across task boundaries.**
   asyncio's `create_task` *drops* contextvars when the new task
   starts; you have to explicitly copy them. anyio's task primitives
   preserve them by default, which matters for request-scoped state
   (request IDs, current user, transaction context).

Third reason — and this is real but less obvious — anyio's
cancellation semantics are noticeably better than asyncio's. Trio's
"cancel scopes" model (which anyio inherits) is harder to
deadlock-by-accident than asyncio's task cancellation.

For applications, none of these matter much: you control the
runtime, you can manage contextvars explicitly, and you can learn
asyncio's cancellation. So application code uses asyncio. Libraries
use anyio.

**How.**

```python
# Library — anyio
import anyio

async def parallel_fetch(urls: list[str]) -> list[bytes]:
    results = [None] * len(urls)
    async with anyio.create_task_group() as tg:
        for i, url in enumerate(urls):
            async def fetch_one(idx=i, u=url):
                results[idx] = await http_get(u)
            tg.start_soon(fetch_one)
    return results

# Run from main — pick backend at the top level
anyio.run(parallel_fetch, ["http://a", "http://b"], backend="asyncio")
# or: backend="trio"
```

In a `pytest`-anyio test setup:

```python
import pytest

@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request):
    return request.param

@pytest.mark.anyio
async def test_my_lib():
    result = await my_lib.fetch("http://example.com")
    assert result.status == 200
```

This matrix runs every test against both backends — catching
"works on asyncio, broken on Trio" regressions automatically.

**When NOT to apply.** Application code that has no need to run on
Trio. The abstraction layer is real cost (one more dependency, a
slightly different API to learn). For apps: asyncio.

---

## PY-067 — Keep strong refs to `create_task` results; or the task vanishes

**What.** When you fire off a task with `asyncio.create_task(...)`
and don't `await` it, the only thing keeping that task alive is a
strong reference. Lose the reference and the garbage collector can
finalize the task mid-flight — silently, with no traceback.

Use the "background tasks set" pattern from the
[asyncio docs](https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task):

```python
import asyncio

background_tasks: set[asyncio.Task] = set()

def fire_and_forget(coro):
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task
```

**Why.** asyncio's event loop only holds **weak references** to the
tasks it tracks. If the only Python-side reference to a task is a
local variable that goes out of scope, GC can collect the task
object before it runs to completion. The coroutine stops mid-await;
no `CancelledError` is raised in the coroutine, no log message
appears, no traceback. The work just doesn't happen.

This is [CPython issue #117379](https://github.com/python/cpython/issues/117379)
and is explicitly called out in the `asyncio.create_task` docs:
"Save a reference to the result of this function, to avoid a task
disappearing mid-execution."

The classic failure mode:

```python
# BROKEN — fire-and-forget that may never finish
async def handler(req):
    asyncio.create_task(audit_log(req))    # no ref held
    return await respond(req)
```

The local `task` (returned by `create_task`) is never assigned;
nothing keeps it alive. Under load, some fraction of `audit_log`
calls will GC mid-await and the audit record will silently never
land. You discover this by noticing the audit log is missing rows.

`add_done_callback(background_tasks.discard)` is the cleanup hook:
when the task finishes, it removes itself from the set so the set
doesn't grow unbounded.

**How.**

```python
import asyncio

class Service:
    def __init__(self):
        self._background: set[asyncio.Task] = set()

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def handle(self, req):
        # audit_log runs concurrently; we don't await it
        self.spawn(audit_log(req))
        return await respond(req)

    async def shutdown(self):
        # Wait for all background work to finish before exit
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)
```

If the work is *important* — must complete before the response is
sent, or its failure should propagate — don't fire-and-forget at
all. Use `await` directly, or put it in an `asyncio.TaskGroup`
(PY-043) so failures surface as an `ExceptionGroup`.

**When NOT to apply.** When you `await` the task before its
reference goes out of scope, the rule is moot — the `await`
guarantees the task lives until it completes. The rule targets
genuine fire-and-forget paths.

---

## PY-068 — Prefer `asyncio.timeout()` (3.11+) over `asyncio.wait_for`

**What.** For applying a timeout to a *block* of async code, use
`asyncio.timeout()` (Python 3.11+) as an async context manager.
Reserve `asyncio.wait_for()` for the narrow case of timing out a
single coroutine and wanting its return value back.

```python
# RIGHT — block-level timeout
import asyncio

async def fetch_with_deadline(url: str) -> bytes:
    async with asyncio.timeout(5.0):
        resp = await http.get(url)
        body = await resp.read()
        return body
```

vs. the older spelling:

```python
# Older — wraps a single coroutine
async def fetch_with_deadline(url: str) -> bytes:
    return await asyncio.wait_for(fetch(url), timeout=5.0)
```

**Why.** Three reasons `asyncio.timeout` is the better default:

1. **No extra task.** `wait_for(coro, timeout=N)` schedules `coro` as a *new* task on the loop, then waits for it. `timeout()` cancels the *current* task instead — no extra scheduling, no extra context. Lower overhead and the traceback on timeout points at the actual blocking line.
2. **Nests correctly.** Multiple nested `async with asyncio.timeout(...)` blocks compose — the innermost deadline that triggers first wins, and outer deadlines stay active afterward. Nested `wait_for` doesn't compose cleanly; you can lose timeouts.
3. **Reschedulable.** The context manager exposes `cm.reschedule(new_deadline)` for adjusting the deadline mid-block — useful for "keep-alive-while-progress-is-happening" patterns:

   ```python
   async with asyncio.timeout(10) as cm:
       async for chunk in stream:
           await process(chunk)
           cm.reschedule(asyncio.get_event_loop().time() + 10)  # reset on progress
   ```

`wait_for` remains the right tool when you specifically want **the
return value of one coroutine, bounded by a timeout**:

```python
result: bytes = await asyncio.wait_for(fetch(url), timeout=5.0)
```

The shape difference: `timeout()` is "bound this region"; `wait_for`
is "bound this expression."

**Important caveat — both forms only fire at `await` points.**
Neither can interrupt synchronous CPU work. A 5-second `timeout()`
block wrapping `json.loads(huge_payload)` will not fire until the
load completes; the loop is stalled and no cancellation can be
delivered. This is the same failure mode as PY-040 — CPU work
belongs in `run_in_executor`.

**How.**

```python
import asyncio

# Simple block timeout
async def fetch_with_deadline(url: str) -> bytes:
    async with asyncio.timeout(5.0):
        return await fetch(url)

# Catching the timeout
async def fetch_or_default(url: str) -> bytes:
    try:
        async with asyncio.timeout(5.0):
            return await fetch(url)
    except TimeoutError:               # 3.11+ — asyncio.TimeoutError aliased to builtin
        return b""

# Timeout against an absolute deadline (instead of "from now")
deadline = asyncio.get_event_loop().time() + 30
async with asyncio.timeout_at(deadline):
    await do_long_work()

# Reschedule the deadline as progress is observed
async with asyncio.timeout(10) as cm:
    async for chunk in stream:
        await process(chunk)
        cm.reschedule(asyncio.get_event_loop().time() + 10)
```

**When NOT to apply.** Two cases:

1. **Python < 3.11.** `asyncio.timeout()` doesn't exist. Use `wait_for` or `anyio.fail_after` (which back-ports the same shape and works on 3.10).
2. **You explicitly want the "run as a new task" semantics of `wait_for`** — for example, when the surrounding code should *not* be cancelled if the timeout fires. This is rare; usually cancelling the current task is what you want.

---

## PY-079 — Free-threaded Python: don't adopt in production yet

**What.** Free-threaded CPython (no GIL —
[PEP 703](https://peps.python.org/pep-0703/), graduated from
"experimental" to "officially supported, optional" in 3.14 via
[PEP 779](https://peps.python.org/pep-0779/)) is real, but
production adoption is still premature. Stay on the standard
GIL-enabled build unless every C extension and pure-Python
dependency in your tree explicitly declares free-threading support.

```bash
# Standard build — what you should be using in production
python3.14

# Free-threaded build — opt-in; runs without the GIL
python3.14t                # ABI suffix `t`
```

**Why.** Three real concerns as of 2026:

1. **Single-threaded overhead.** Free-threaded CPython carries a single-threaded overhead vs. the GIL build — down to roughly ~5–10% in 3.14 (from higher in 3.13), improving but not gone. For workloads that don't actually run threads in parallel — most web servers, async services, batch scripts — you pay the tax for no benefit.
2. **C extensions silently re-enable the GIL.** A C extension built without `Py_mod_gil = Py_MOD_GIL_NOT_USED` causes the free-threaded interpreter to re-enable the GIL at import time, with only a warning. You think you're running GIL-free; you're not. Auditing this across a large dependency tree is genuine work, and any new transitive dep can re-introduce the GIL.
3. **Per-package support is still uneven.** numpy, pandas, lxml, pillow, and other heavy C-extension packages have shipped free-threaded wheels at various dates; many smaller packages have not. Track support at <https://py-free-threading.github.io/>.

When you *do* migrate, do it in a non-production environment first,
audit `sys._is_gil_enabled()` after importing every dependency, and
benchmark — sometimes the GIL-disabled wins are smaller than
expected because the workload was never GIL-bound in the first
place.

**How.** For evaluation:

```bash
# Install a free-threaded interpreter
uv python install 3.14t

# Confirm it's actually free-threaded after imports
uv run --python 3.14t python -c "
import sys, numpy, pandas
print('gil_enabled:', sys._is_gil_enabled())
"
```

For libraries that want to declare free-threading support, add to
`pyproject.toml`:

```toml
[tool.cibuildwheel]
free-threaded-support = true     # if you ship C extensions via cibuildwheel
```

and in C extension modules:

```c
static PyModuleDef_Slot module_slots[] = {
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},
    {0, NULL}
};
```

**When NOT to apply.** Two cases:

1. **Pure-Python CPU-bound workload with measured parallelism wins.** If you've benchmarked the workload, every dependency is free-thread-clean, and the speedup is real, free-threaded Python may be worth the tax. Validate, don't assume.
2. **Experimental / research environments.** The whole point of PEP 779's "officially supported, optional" status is to encourage experimentation. Just don't ship it to production unless the above checks all pass.

## PY-083 — Use `InterpreterPoolExecutor` for CPU-bound work on Python 3.14+

**What.** `concurrent.interpreters.InterpreterPoolExecutor` (Python 3.14,
PEP 734) runs each worker in its own subinterpreter on a background
thread — process-like isolation (each interpreter has independent state)
at closer-to-thread overhead, with no separate process to spawn.

**Why.** `ProcessPoolExecutor` pays full process-startup and
pickling-IPC cost. For CPU-bound *pure-Python* work where that startup
cost dominates, an interpreter pool is a lighter option with the same
"no shared GIL contention" benefit. It complements PY-040 (asyncio is
for I/O; CPU-bound work goes to an executor) by adding a third executor
choice.

**How.**

```python
from concurrent.interpreters import InterpreterPoolExecutor

with InterpreterPoolExecutor() as pool:
    results = list(pool.map(cpu_heavy, chunks))
```

**When NOT to apply.** Dependencies that aren't subinterpreter- or
free-threading-compatible (many C extensions still aren't). Work needing
shared mutable state — inter-interpreter communication goes through
`interpreters.Queue` with serialization, so it's not a drop-in for
threads. On pre-3.14, use `ProcessPoolExecutor`.

---

## PY-084 — Use `asyncio.get_running_loop()`, never `asyncio.get_event_loop()`

**What.** `asyncio.get_event_loop()` **raises `RuntimeError`** on Python
3.14+ when there is no running loop (it was a `DeprecationWarning` from
3.10). Inside async code use `asyncio.get_running_loop()`; from sync code
use `asyncio.run(main())`.

**Why.** Any code calling `get_event_loop()` outside a running loop
crashes outright on 3.14 — a hard regression for libraries and scripts
that used the old implicit-loop-creation behavior. `get_running_loop()`
errors loudly only when there genuinely is no loop (always a bug), and
`asyncio.run()` owns the loop lifecycle correctly from sync entry points.

**How.**

```python
# inside a coroutine
loop = asyncio.get_running_loop()
await loop.run_in_executor(pool, blocking_fn)

# sync entry point
asyncio.run(main())          # not get_event_loop().run_until_complete(...)
```

Grep for `get_event_loop()` when raising your floor to 3.14+.

**When NOT to apply.** No real exception — `get_event_loop()` is the
wrong call. The only legacy context is *inside* a running loop, where
`get_running_loop()` is strictly better anyway.

---

## PY-085 — Introspect stuck async apps with `python -m asyncio ps` / `pstree`

**What.** Python 3.14 ships `python -m asyncio ps <pid>` and
`python -m asyncio pstree <pid>` — CLI tools that attach to a running
process and print all active asyncio tasks, their coroutine stacks, and
await chains, with no code changes. Programmatic equivalents:
`asyncio.print_call_graph()` / `capture_call_graph()`; `pdb.set_trace_async()`
for interactive async debugging.

**Why.** Diagnosing a deadlocked or hung async service used to mean
adding ad-hoc logging or a task dump and redeploying. `pstree <pid>`
shows the await graph of a *live* process directly, so you can see which
task is stuck on what without touching the code.

**How.**

```bash
python -m asyncio pstree 12345    # await-chain tree for a running process
python -m asyncio ps 12345        # flat task list
```

**When NOT to apply.** Pre-3.14 runtimes (the subcommands don't exist),
and environments where you can't attach to the target process (locked-down
containers without ptrace).

---
