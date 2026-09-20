# FAPI dependency-injection rules

Detailed entries for `FAPI-030..FAPI-032`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI dependencies docs](https://fastapi.tiangolo.com/tutorial/dependencies/),
[dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/),
and [OAuth2 scopes](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/).

---

## FAPI-030 — Declare dependencies as `Annotated[T, Depends(fn)]` and reuse via type aliases

**What.** Write dependencies as `param: Annotated[T, Depends(fn)]`, and
hoist recurring ones into a module-level alias
(`CurrentUser = Annotated[User, Depends(get_current_user)]`). Prefer this
over the legacy `param: T = Depends(fn)` default form.

**Why.** The `= Depends(fn)` form confuses type checkers — the parameter
reads as having a dependency object as its default, so mypy/pyright lose
the real type and IDE autocompletion degrades down the call chain.
`Annotated` keeps the type and the dependency metadata as separate
concerns, so both static analysis and FastAPI see what they need. The
alias also kills the repetition of spelling the same dependency on twenty
routes.

**How.**

```python
from typing import Annotated
from fastapi import Depends

CurrentUser = Annotated[User, Depends(get_current_user)]

@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return user
```

**When NOT to apply.** Nothing real — `Annotated` is the current
recommended form for all FastAPI ≥0.95. The only reason to see
`= Depends(...)` is an old codebase mid-migration.

---

## FAPI-031 — Wrap `yield` dependencies in `try/finally` so cleanup runs on error

**What.** Any dependency that acquires a resource (DB session, file
handle, HTTP client) must `yield` it and release it in a `finally` block —
never rely on reaching a bare cleanup line after the `yield`.

**Why.** When a path operation raises (an `HTTPException`, a validation
error, anything), FastAPI resumes the dependency *after* the `yield` — but
a bare `await session.close()` sitting after the `yield`, not in a
`finally`, is skipped if the exception propagates through it. The
connection leaks back to the pool and never returns; under load the pool
exhausts and the service wedges.

**How.**

```python
async def get_db() -> AsyncIterator[AsyncSession]:
    session = AsyncSession(engine)
    try:
        yield session
    finally:
        await session.close()
```

**When NOT to apply.** Dependencies that don't own a resource (a function
returning a computed value with nothing to release) don't need
`try/finally` — there's nothing to clean up.

---

## FAPI-032 — Use `Security(fn, scopes=[...])` (not `Depends`) for OAuth2 scope-bearing auth

**What.** When a route requires specific OAuth2 scopes, declare the auth
dependency with `Security(get_current_user, scopes=["items:write"])`
rather than `Depends(get_current_user)`. `Security` is `Depends` plus
scope metadata wired into the OpenAPI schema.

**Why.** `Depends` on a scope-aware function leaves the required scopes
undeclared in OpenAPI. Swagger UI then doesn't know which scopes to
request in the auth flow, and generated clients can't see the scope
requirement — the authorization UX silently breaks even though the
server-side check works. `Security(..., scopes=...)` propagates the
requirement into the spec's security definitions.

**How.**

```python
from fastapi import Security

@router.post("/items/")
async def create_item(
    user: Annotated[User, Security(get_current_user, scopes=["items:write"])],
) -> ItemOut:
    ...
```

`SecurityScopes` inside `get_current_user` lets you read and enforce the
declared scopes.

**When NOT to apply.** Auth dependencies that don't use OAuth2 scopes (a
plain API-key check, a boolean "is logged in" gate) — plain `Depends` is
correct there; `Security` only earns its place when scopes are involved.
