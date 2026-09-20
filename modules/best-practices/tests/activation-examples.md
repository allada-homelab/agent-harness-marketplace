# Activation expectations

Frozen "this user query should activate this skill" expectations.
Used as a human-readable regression check — editing a skill's
`description:` field is the most common way to silently break
activation, and this file is the way to notice.

Not an automated test. To verify, read each `description:` field
and ask: would a harness reasonably match the listed queries to this
skill? If a query no longer plausibly matches, either fix the
description or update the expectation here with a reason.

---

## meta-best-practices

Should activate:

- "What's the rule-ID format for the best-practices library?"
- "How do I add a new rule to containers-best-practices?"
- "What does severity 'high' mean in this library?"
- "Add a rule PY-001 for the new python skill"
- "How are best-practices skills structured?"

Should NOT activate:

- Generic questions about software best practices without reference to this library.
- Container or Docker questions (those route to containers-best-practices).

## containers-best-practices

Should activate:

- "Review my Dockerfile"
- "How should I set up a dev container for this project?"
- "Audit my compose.yml"
- "Why is my Docker image so large?"
- "Set up multi-stage build for this Python service"
- "What's DOCKER-005?" (rule-ID match)
- "Is `COPY .env` safe?" (SEC-012 keyword match)
- "How should I install uv in this Dockerfile?" (container-side uv, UV-* family)

Should NOT activate:

- "How do I structure a Python project?" (→ python-best-practices, once that exists)
- "Should I commit uv.lock?" (→ uv-best-practices)
- "What's the right `[tool.uv]` config?" (→ uv-best-practices)

## uv-best-practices

Should activate:

- "Should I commit uv.lock?"
- "What's the difference between `--locked` and `--frozen`?"
- "How do dependency groups work in uv?"
- "Set up a uv workspace"
- "Migrate this project from poetry to uv"
- "How do I pin my Python version?" (also triggers python-best-practices via PY-050)
- "Should ruff go in `uv tool install` or `uv add --dev`?" (also python-best-practices via PY-020)
- "What's UVP-011?" (rule-ID match)
- "Cache uv in GitHub Actions"

Should NOT activate:

- "How should I install uv in this Dockerfile?" (→ containers-best-practices, UV-* family)
- "Multi-stage Dockerfile with uv" (→ containers-best-practices)
- "What's the best way to structure my Python project's `src/` directory?" (→ python-best-practices)

## python-best-practices

Should activate:

- "Should I use src/ layout for my Python package?"
- "What's the right way to set up `__init__.py`?"
- "How should I configure mypy / pyright in strict mode?"
- "Protocol vs ABC for this interface?"
- "TypedDict vs dataclass vs Pydantic for this data?"
- "What ruff rules should I enable?"
- "Set up pre-commit with ruff"
- "How do I parametrize this pytest test?"
- "What's the difference between `pytest-asyncio` and `anyio` plugin?"
- "When should I use `TaskGroup` vs `asyncio.gather`?"
- "How do I configure structlog?"
- "Should I commit logging config in pyproject.toml?"
- "Set up PyPI publishing via OIDC / Trusted Publishing"
- "What's the right `[project]` metadata for PyPI?"
- "What's PY-016?" (rule-ID match)

Should NOT activate:

- "Should I commit uv.lock?" (→ uv-best-practices, UVP-010)
- "Set up uv workspace" (→ uv-best-practices, UVP-006)
- "How to install uv in Dockerfile" (→ containers-best-practices, UV-001)

## fastapi-best-practices

Should activate:

- "Review my FastAPI app structure"
- "How should I organize routers in FastAPI?"
- "Set up OAuth2 / JWT auth in FastAPI"
- "Should this route be `async def` or `def`?"
- "How do I use lifespan instead of on_event?"
- "Inject settings into a FastAPI dependency"
- "Test a FastAPI endpoint with an async client"
- "What's FAPI-070?" (rule-ID match)

Should NOT activate:

- General Python typing/linting/packaging questions with no FastAPI context (→ python-best-practices).
- Flask/Django/Starlette-only questions with no FastAPI involved.
- "Dockerfile for a FastAPI app" → the container packaging routes to containers-best-practices; FastAPI-specific app rules activate alongside only if app code is in context.

Cross-skill ambiguity is acceptable when both apply — "Dockerfile for
a uv-based Python project with strict typing" should activate
`containers-best-practices`, `uv-best-practices`, and
`python-best-practices`. A FastAPI service with async SQLAlchemy and
Pydantic models activates `fastapi-best-practices` alongside
`python-best-practices`. The user benefits from rules from all sides.

---

## go-best-practices

Should activate:

- "Review this Go service" / "Fix this .go file"
- "How should I structure my Go module / packages?"
- "How do I wrap errors so errors.Is still works?"
- "What's the right way to avoid goroutine leaks?"
- "Set timeouts on my net/http server"
- "Is this SQL injection-safe in Go?"
- "Set up golangci-lint / staticcheck for a Go repo"
- "Write table-driven tests for this function"
- "What's GO-004?" (rule-ID match)

Should NOT activate:

- "Dockerfile for a Go service" (→ containers-best-practices).
- "gRPC status codes / interceptors for my service" (→ grpc-best-practices; go-best-practices activates alongside only if Go code is in context).

## grpc-best-practices

Should activate:

- "Review my .proto files"
- "Which gRPC status code should I return?"
- "How do I propagate deadlines across services?"
- "How do I handle client disconnects in a server stream?"
- "Add auth / logging / recovery interceptors to my gRPC server"
- "Validate requests with protovalidate"
- "Set up buf lint + breaking checks in CI"
- "Enable grpcurl / reflection in dev"
- "What's GRPC-007?" (rule-ID match)

Should NOT activate:

- REST/HTTP API questions with no gRPC involvement (→ python-best-practices / go-best-practices / fastapi-best-practices by language).
- "Dockerfile for a gRPC service" (→ containers-best-practices).

---

When adding a new skill, append a section here with the same shape
(Should activate / Should NOT activate). When editing a description
field, re-read the relevant section to verify expectations still hold.
