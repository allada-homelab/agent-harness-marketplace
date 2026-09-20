# FAPI error-handling rules

Detailed entries for `FAPI-050..FAPI-053`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI error-handling docs](https://fastapi.tiangolo.com/tutorial/handling-errors/)
and [exception handlers](https://fastapi.tiangolo.com/advanced/exception-handlers/).

---

## FAPI-050 — Register handlers against `StarletteHTTPException` to also catch routing 404/405

**What.** `fastapi.HTTPException` subclasses
`starlette.exceptions.HTTPException`. Starlette's router itself raises the
*base* class for "route not found" (404) and "method not allowed" (405).
Register your custom HTTP-error handler against
`from starlette.exceptions import HTTPException as StarletteHTTPException`.

**Why.** A handler bound to `fastapi.HTTPException` catches only what your
code raises explicitly. Requests to a nonexistent path bypass it and get
Starlette's raw default 404, so your API returns two different error
envelopes depending on whether the failure was application-level or
routing-level — and clients can't rely on a consistent shape.

**How.**

```python
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exception_handlers import http_exception_handler

@app.exception_handler(StarletteHTTPException)
async def on_http_exception(request, exc):
    # reuse FastAPI's default formatting, or build your own envelope
    return await http_exception_handler(request, exc)
```

**When NOT to apply.** If you're satisfied with FastAPI's default error
bodies, you don't need a custom handler at all — the rule only matters
once you standardize on a custom envelope and need it applied uniformly.

---

## FAPI-051 — Override `RequestValidationError` to stabilize the 422 response shape

**What.** Install `@app.exception_handler(RequestValidationError)` when
consumers depend on a stable error envelope. FastAPI's default 422 body
(`{"detail": [...pydantic error objects...]}`) exposes Pydantic's internal
error structure.

**Why.** Pydantic's error format is an implementation detail that changed
between v1 and v2. A client that parsed the default 422 will break on a
Pydantic upgrade unless you own and stabilize the shape yourself. A custom
handler decouples your public error contract from your Pydantic version.

**How.**

```python
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def on_validation_error(request, exc: RequestValidationError):
    errors = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
              for e in exc.errors()]
    return JSONResponse(status_code=422, content={"errors": errors})
```

**When NOT to apply.** Internal APIs where you control both ends and pin
Pydantic — the default 422 is informative and not worth replacing.

---

## FAPI-052 — Register a catch-all `Exception` handler that logs and returns a safe `500`

**What.** Install `@app.exception_handler(Exception)` that logs the
exception (with any request correlation ID) and returns a generic
`500` body. Don't let unexpected exceptions reach Starlette's default.

**Why.** With `debug=True`, Starlette renders the full traceback into the
HTTP response — a data-exposure bug if it ever ships enabled. Even in
production, an explicit handler guarantees consistent structured logging
and a safe, uniform error body instead of relying on framework defaults
that differ by environment.

**How.**

```python
import logging
logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def on_unhandled(request, exc):
    logger.exception("unhandled error", extra={"path": request.url.path})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

Register it alongside the `StarletteHTTPException` and
`RequestValidationError` handlers — FastAPI dispatches by exception type,
so the specific handlers still win for their types.

**When NOT to apply.** Never skip it in production. The one caveat:
don't let the catch-all swallow `HTTPException`/validation errors — those
have their own handlers and should keep their intended status codes, not
collapse to 500.

---

## FAPI-053 — Use a structured `detail` (dict with a code) for machine-readable errors

**What.** `HTTPException(detail=...)` accepts any JSON-serializable value.
For APIs consumed by code (not just humans), prefer
`detail={"code": "ITEM_NOT_FOUND", "item_id": item_id}` over a bare
string.

**Why.** A string detail forces clients to pattern-match natural-language
messages to identify an error type — brittle, and it breaks the moment
you reword the message or localize it. A stable `code` lets clients branch
deterministically and lets you change human-facing text freely.

**How.**

```python
raise HTTPException(
    status_code=404,
    detail={"code": "ITEM_NOT_FOUND", "item_id": item_id},
)
```

Define an error-code enum once if the API has many error types, so codes
stay consistent.

**When NOT to apply.** Small internal or human-facing endpoints where no
programmatic client branches on error type — a clear string is simpler
and fine.
