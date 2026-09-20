# FAPI testing rules

Detailed entries for `FAPI-080..FAPI-082`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI testing docs](https://fastapi.tiangolo.com/tutorial/testing/),
[async tests](https://fastapi.tiangolo.com/advanced/async-tests/),
and [testing events/lifespan](https://fastapi.tiangolo.com/advanced/testing-events/).

General pytest mechanics (fixtures, parametrize, async mode) live in
[`python-best-practices`](../../python-best-practices/references/testing.md).

---

## FAPI-080 — Use `TestClient` for sync tests, `httpx.AsyncClient` + `ASGITransport` for async

**What.** Use `fastapi.testclient.TestClient` in ordinary synchronous test
functions. When the test itself must `await` (async DB assertions, async
fixtures), switch to
`httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`
inside an async test.

**Why.** `TestClient` drives the ASGI app through a worker thread and
can't be `await`ed; using it from inside an `async def` test attaches the
app to a different event loop than the test, producing intermittent
`RuntimeError: Task got Future attached to a different loop`. The
`AsyncClient` + `ASGITransport` pair runs in-process on the test's own
loop with no network.

**How.**

```python
import pytest
from httpx import AsyncClient, ASGITransport

@pytest.mark.anyio
async def test_create_item():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/items/", json={"name": "foo"})
    assert resp.status_code == 201
```

**When NOT to apply.** Synchronous tests of synchronous behavior — reach
for `TestClient`, it's simpler and you don't need the async ceremony.

---

## FAPI-081 — Swap dependencies with `app.dependency_overrides`, not monkeypatching

**What.** Replace dependencies in tests via
`app.dependency_overrides[get_db] = lambda: test_session`. Always clear
them in teardown (`app.dependency_overrides.clear()` or a scoped fixture).

**Why.** `unittest.mock.patch` on a dependency function patches a name,
but FastAPI captured the original callable by identity at route-definition
time — the patch may not intercept the reference FastAPI actually calls,
so the test silently runs against the real database. `dependency_overrides`
is the framework's supported, identity-correct substitution point.

**How.**

```python
@pytest.fixture
def client(test_session):
    app.dependency_overrides[get_db] = lambda: test_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

**When NOT to apply.** Code that isn't wired through FastAPI's dependency
system (a plain module function with no `Depends`) — there's nothing to
override, so a normal fixture or `monkeypatch` is appropriate.

---

## FAPI-082 — Enter `TestClient(app)` as a context manager so `lifespan` runs in tests

**What.** Use `with TestClient(app) as client:` rather than a bare
`client = TestClient(app)` so the app's `lifespan` startup/shutdown runs
during the test. For `AsyncClient`, use `asgi-lifespan`'s `LifespanManager`.

**Why.** The bare constructor does not trigger `lifespan`. If startup
initializes a pool, model, or `app.state` resource the routes depend on,
tests that skip it fail with `AttributeError` on `app.state.x` — or worse,
run against half-initialized state. The context-manager form mirrors what
production startup does.

**How.**

```python
def test_health():
    with TestClient(app) as client:        # runs lifespan
        assert client.get("/health").status_code == 200

# async:
from asgi_lifespan import LifespanManager
async with LifespanManager(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ...
```

**When NOT to apply.** An app with no `lifespan` (or whose lifespan does
nothing the test touches) doesn't strictly need the `with` form — but
using it costs nothing and keeps tests robust if a lifespan is added
later.
