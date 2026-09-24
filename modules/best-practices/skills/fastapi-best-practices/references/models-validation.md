# FAPI models & validation rules

Detailed entries for `FAPI-010..FAPI-014`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI response-model docs](https://fastapi.tiangolo.com/tutorial/response-model/),
[FastAPI custom-response docs](https://fastapi.tiangolo.com/advanced/custom-response/),
and the [Pydantic v2 config docs](https://docs.pydantic.dev/latest/concepts/config/).

---

## FAPI-010 — Configure Pydantic v2 models with `model_config = ConfigDict(...)`, not inner `class Config`

**What.** All Pydantic v2 model configuration goes in a class-level
`model_config = ConfigDict(...)`. The v1 inner `class Config:` still
works in v2 but is deprecated (`PydanticDeprecatedSince20`), and v1 keys
that v2 renamed, such as `orm_mode`, are **ignored** with only a
`UserWarning`.

**Why.** A warning is easy to miss. `class Config: orm_mode = True` on a
v2 model imports fine and does nothing ("'orm_mode' has been renamed to
'from_attributes'"), so the model looks correct until you notice ORM
attributes aren't being read off your SQLAlchemy objects. The v2 spelling
is `model_config = ConfigDict(from_attributes=True)`; without it,
`Model.model_validate(orm_obj)` won't pull attributes. Run tests with
warnings as errors (`filterwarnings = ["error"]`, PY-030) so both
warnings fail the suite instead of scrolling past.

**How.**

```python
from pydantic import BaseModel, ConfigDict

class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
```

**When NOT to apply.** Never on v2 — `class Config` is deprecated
there. If you're still on Pydantic v1 (FastAPI <0.100), `class Config` is
correct, but that's a migration to schedule, not a style choice.

---

## FAPI-011 — Use separate input and output models so secrets never leak into responses

**What.** Don't reuse one model for both the request body and the
response when it carries fields that must not go back to the client
(passwords, internal flags, audit columns). Define `UserIn` with the
sensitive field and a `UserOut`/`BaseUser` without it, and use the output
model as the return annotation.

**Why.** A single `User` model returned from a create endpoint echoes the
submitted password straight back. With a separate output model, FastAPI
does the protecting: it filters the response to the fields of the
declared return type (or `response_model`), so returning the `UserIn`
instance still sends only `BaseUser`'s fields. Type checkers don't catch
this: `UserIn` is a subclass of `BaseUser`, so "The editor, mypy, and
other tools won't complain about this"
([FastAPI — Return Type and Data Filtering](https://fastapi.tiangolo.com/tutorial/response-model/#return-type-and-data-filtering)).
The filtering is runtime behavior, so cover it with a test that asserts
the secret field is absent from the response.

**How.**

```python
class BaseUser(BaseModel):
    username: str
    email: str

class UserIn(BaseUser):
    password: str          # inbound only

@router.post("/users/")
async def create_user(user: UserIn) -> BaseUser:   # FastAPI filters password out
    ...
```

**When NOT to apply.** Models with no sensitive or internal fields (a
public `Tag` with `id`/`name`) can be shared input and output — the
split is overhead with nothing to protect.

---

## FAPI-012 — Prefer a return-type annotation over `response_model=` when the shapes match

**What.** When the handler returns exactly the declared type, annotate
the return (`-> Item`, `-> list[Item]`) and drop `response_model=`.
Reserve `response_model=` for the case where the *returned object* differs
from what should be serialized (returning an ORM row or `dict` to be
coerced).

**Why.** The return annotation gives type checkers, the IDE, and Pydantic
the same filtering/validation information `response_model=` does — plus
static analysis FastAPI can't get from a decorator argument. A redundant
`response_model=Item` on a `-> Item` handler is noise, and if the two ever
drift apart the behavior gets confusing.

**How.**

```python
@router.get("/items/{item_id}")
async def get_item(item_id: int) -> Item:      # no response_model needed
    return await load_item(item_id)

# response_model earns its place when the return type is broader:
@router.get("/raw", response_model=Item)
async def raw() -> Any:
    return some_orm_row
```

**When NOT to apply.** When you deliberately return a wider type
(`-> Any`, `-> dict`, an ORM object) and want FastAPI to coerce/filter it
to a narrower schema — that's exactly what `response_model=` is for.

---

## FAPI-013 — Set `response_model_exclude_unset=True` for sparse/partial-record responses

**What.** On endpoints returning records where many optional fields are
typically absent (a sparse profile), set
`response_model_exclude_unset=True` so only the fields the handler
actually set are serialized.

**Why.** Without it, every optional field with a default (`None`, `""`,
`[]`) appears in every response. That bloats payloads and erases the
distinction between "the server set this to `None`" and "the server never
populated it" — a distinction clients often need for `PATCH`-style
merges.

**How.**

```python
@router.get("/items/{item_id}", response_model_exclude_unset=True)
async def get_item(item_id: int) -> Item:
    return await load_item(item_id)
```

`response_model_exclude_none=True` and `_exclude_defaults=True` are
related knobs for adjacent cases.

**When NOT to apply.** Clients that expect a fixed, fully-populated schema
(strongly-typed generated clients that don't tolerate missing keys) are
better served by always emitting every field. Don't toggle this globally
without checking consumers.

---

## FAPI-014 — Pair `response_class=` with `response_model=None` when returning a `Response` directly

**What.** When a path operation returns a `Response` subclass
(`StreamingResponse`, `FileResponse`, a custom response), declare
`response_class=StreamingResponse` so OpenAPI documents the media type,
and set `response_model=None` to suppress the default JSON schema.

**Why.** Returning a `Response` without `response_class=` leaves the
OpenAPI docs showing no/incorrect response body, so Swagger UI and
generated clients don't know what to expect. And if the route is also
typed to return something Pydantic-shaped, FastAPI will try to validate
the raw `Response` against it — `response_model=None` turns that off.

**How.**

```python
from fastapi.responses import StreamingResponse

@router.get("/export", response_class=StreamingResponse, response_model=None)
async def export() -> StreamingResponse:
    return StreamingResponse(row_generator(), media_type="text/csv")
```

**When NOT to apply.** Ordinary JSON endpoints returning Pydantic models
or dicts — let FastAPI's default `JSONResponse` and schema generation do
their job; don't set `response_class` you don't need.
