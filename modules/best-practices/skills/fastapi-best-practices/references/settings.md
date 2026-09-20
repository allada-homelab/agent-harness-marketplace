# FAPI settings rules

Detailed entries for `FAPI-020..FAPI-022`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI settings docs](https://fastapi.tiangolo.com/advanced/settings/)
and the
[pydantic-settings docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

---

## FAPI-020 — Use `pydantic-settings` `BaseSettings` for config, not scattered `os.getenv`

**What.** Application config (DB URL, secret key, feature flags, external
service URLs) lives in a `class Settings(BaseSettings)` with typed
fields. `pydantic-settings` reads env vars and `.env` files, validates
types, and rejects a missing required value at startup.

**Why.** `os.getenv("DATABASE_URL")` returns `str | None` with no
validation. A misconfigured deployment hands `None` to the engine and
crashes on the first query — at request time, on a user, not at boot.
`BaseSettings` fails fast with a clear validation error before the app
serves anything, turning a 3 a.m. incident into a failed deploy.

**How.**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")
    db_url: str
    secret_key: str
    debug: bool = False
```

`pydantic-settings` is a separate package since Pydantic v2 — add it
explicitly (`uv add pydantic-settings`); it is not in `pydantic` core.

**When NOT to apply.** A one-off script reading a single env var doesn't
need a settings class. The rule is for the application's configuration
surface, not every individual `getenv`.

---

## FAPI-021 — Wrap `Settings()` in `@lru_cache` and inject it via `Depends`

**What.** Define `@lru_cache` `def get_settings() -> Settings: return
Settings()` and inject it as `Annotated[Settings, Depends(get_settings)]`.
Don't instantiate `Settings()` at module import time or per request.

**Why.** Module-level instantiation freezes config at import, so tests
can't override env vars after the import runs. Per-request instantiation
re-reads and re-validates the `.env` file on every call. `@lru_cache`
gives a process-singleton that's still injectable — and overridable in
tests via `app.dependency_overrides[get_settings]`.

**How.**

```python
from functools import lru_cache

@lru_cache
def get_settings() -> Settings:
    return Settings()

@router.get("/info")
async def info(settings: Annotated[Settings, Depends(get_settings)]):
    return {"debug": settings.debug}

# in tests
app.dependency_overrides[get_settings] = lambda: Settings(db_url="sqlite://", secret_key="x")
```

**When NOT to apply.** Config that must hot-reload at runtime (rare for a
typical web service) shouldn't be cached — but reach for a deliberate
reload mechanism, not per-request re-parsing.

---

## FAPI-022 — Type secret fields as `SecretStr`

**What.** Fields holding secrets — API keys, the JWT signing key, DB
passwords — are typed `SecretStr` in `BaseSettings`. Read the raw value
only at the point of use with `.get_secret_value()`.

**Why.** A plain `str` secret shows up in `repr()`, in logs that dump the
settings object, and in exception tracebacks. `SecretStr` renders as
`**********` in all default string conversions, so an accidental
`logger.info(settings)` or a traceback can't spill the credential.

**How.**

```python
from pydantic import SecretStr

class Settings(BaseSettings):
    jwt_secret: SecretStr

# at the use site only
token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
```

**When NOT to apply.** Non-secret config (hostnames, ports, feature
flags) — `SecretStr` there just adds `.get_secret_value()` noise for no
protection.
