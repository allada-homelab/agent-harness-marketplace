# FAPI security rules

Detailed entries for `FAPI-060..FAPI-063` and `API-001`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI OAuth2/JWT tutorial](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
and [OAuth2 with scopes](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/).

---

## FAPI-060 — Hash passwords with Argon2 via `pwdlib`; never plaintext, MD5, or SHA-1

**What.** Use `pwdlib` for password hashing and verification:
`PasswordHash.recommended()` selects Argon2. FastAPI's own security
tutorial uses `pwdlib[argon2]` (it moved off `passlib[bcrypt]`).

**Why.** Plaintext, MD5, and SHA-1 password storage have been cracked in
bulk from real breaches (LinkedIn 2012, RockYou). Fast general-purpose
hashes are GPU-crackable at scale; Argon2 is memory-hard, the Password
Hashing Competition winner, and the current OWASP recommendation. bcrypt
remains acceptable, but new code should default to Argon2.

**How.**

```python
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()

hashed = password_hash.hash(plain_password)            # at registration
ok = password_hash.verify(plain_password, hashed)      # at login
```

Install with `uv add "pwdlib[argon2]"`.

**When NOT to apply.** Migrating an existing bcrypt store can keep
verifying bcrypt hashes while re-hashing to Argon2 on next successful
login — don't force a flag-day rehash you can't do (you never have the
plaintext at rest). Never an excuse to keep MD5/SHA-1.

---

## FAPI-061 — Verify against a dummy hash when the user lookup misses (timing attack)

**What.** In `authenticate_user`, if the username isn't found, still run a
hash verification against a constant dummy hash before returning failure.
Don't short-circuit out before any hashing happens.

**Why.** Hashing is deliberately slow; a missing user that returns
immediately is measurably faster than a found user whose (wrong) password
gets hashed and compared. That timing difference lets an attacker
enumerate valid usernames. Running the verification unconditionally makes
both paths take the same time.

**How.**

```python
DUMMY_HASH = password_hash.hash("dummy-password")   # module level

def authenticate_user(username: str, password: str) -> User | None:
    user = repo.get_by_username(username)
    if user is None:
        password_hash.verify(password, DUMMY_HASH)  # burn the same time
        return None
    if not password_hash.verify(password, user.hashed_password):
        return None
    return user
```

**When NOT to apply.** Threat models where username enumeration is a
non-issue because usernames are already public (e.g. they're email
addresses you publish) — though the cost of the dummy verify is tiny, so
there's little reason to drop it.

---

## FAPI-062 — Never put secrets, PII, or session state in a JWT payload

**What.** A JWT is base64-encoded and signed, **not encrypted** — anyone
holding the token can read the payload. Store only the minimum
non-sensitive claims needed to identify the subject and authorize:
`sub`, `exp`, and optionally `scope`. Never passwords, emails, or
business data.

**Why.** Tokens travel in headers, sit in browser storage or cookies,
land in proxy access logs, and show up in packet captures. A token
carrying PII becomes a data-leak vector every place it's logged or
cached. Look up everything else by `sub` server-side.

**How.**

```python
to_encode = {"sub": str(user.id), "exp": expire, "scope": " ".join(scopes)}
token = jwt.encode(to_encode, settings.jwt_secret.get_secret_value(), algorithm="HS256")
```

Use **PyJWT** (`pyjwt`) for `jwt.encode` / `jwt.decode` — FastAPI's
current security tutorial uses it; the older `python-jose` is effectively
unmaintained. Always set `exp`; fetch profile data in `get_current_user`
from the subject, not the token.

**When NOT to apply.** Never store secrets/PII in the payload. If you
genuinely must carry confidential data in a token, that's JWE (encrypted
JWT), a different mechanism — not a signed JWT with extra claims.

---

## FAPI-063 — Point `OAuth2PasswordBearer(tokenUrl=...)` at the real token endpoint path

**What.** The `tokenUrl` passed to `OAuth2PasswordBearer` must match the
path of your actual token-issuing endpoint (relative to the app root),
including any prefix the app is mounted under.

**Why.** `tokenUrl` is what Swagger UI's "Authorize" button and generated
SDK clients use to discover where to send credentials. A wrong value
(`tokenUrl="token"` when the endpoint is at `/api/v1/token`) makes the
interactive auth flow POST to the wrong path and 404 — the API works but
nobody can log in through the docs.

**How.**

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/token")

@router.post("/api/v1/token")
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    ...
```

Behind a proxy prefix, prefer setting `root_path` (FAPI-091) and a
relative `tokenUrl` so the two stay in sync.

**When NOT to apply.** No exception — if you use `OAuth2PasswordBearer`,
`tokenUrl` has to point at the real endpoint. The only variation is
whether you express it as an absolute path or rely on `root_path`.

---

## API-001 — Compare bearer tokens with `hmac.compare_digest` on bytes, never `==`

**What.** A shared-token auth dependency encodes the presented bearer
token and the configured one to bytes and compares them with
`hmac.compare_digest`. A missing or non-Bearer header compares as `b""`,
so every failure takes the same path to one 401 with
`WWW-Authenticate: Bearer`.

**Why.** `==` on strings or bytes returns at the first differing byte.
Response time then leaks how much of a guess matched, so a token can be
recovered a byte at a time over many requests. `compare_digest` doesn't
short-circuit on content. Comparing bytes rather than `str` matters as
well: with `str` arguments `compare_digest` accepts ASCII only and raises
`TypeError` otherwise. Starlette decodes headers as latin-1, so a client
could turn a bad token into a 500 instead of a 401.
Source: https://docs.python.org/3.14/library/hmac.html#hmac.compare_digest

> This function uses an approach designed to prevent timing analysis by avoiding content-based short circuiting behaviour, making it appropriate for cryptography.

> *a* and *b* must both be of the same type: either "str" (ASCII only, as e.g. returned by "HMAC.hexdigest()"), or a *bytes-like object*.

> If *a* and *b* are of different lengths, or if an error occurs, a timing attack could theoretically reveal information about the types and lengths of *a* and *b*—but not their values.

**How.**

```python
import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)  # a missing header reaches our single 401 path


async def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = request.app.state.settings.api_token.get_secret_value().encode()
    given = credentials.credentials.encode() if credentials else b""
    if not hmac.compare_digest(given, expected):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

Attach it to the protected router with
`APIRouter(dependencies=[Depends(require_token)])` (FAPI-002).

**When NOT to apply.** Lengths still leak, so use a long, fixed-length
random token. A single shared token authenticates the caller, not a
user. Per-user auth needs OAuth2/JWT or sessions (FAPI-060..FAPI-063),
and the same constant-time rule applies wherever a secret is compared.
