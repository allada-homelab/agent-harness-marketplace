# PY logging rules

Detailed entries for `PY-050..PY-056` plus `PY-076` (async-safe
logging via `QueueHandler`). Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[Python logging HOWTO](https://docs.python.org/3/howto/logging.html),
[Python logging cookbook](https://docs.python.org/3/howto/logging-cookbook.html),
[QueueHandler / QueueListener docs](https://docs.python.org/3/library/logging.handlers.html#queuehandler),
[structlog docs](https://www.structlog.org/),
and [Twelve-Factor App §11](https://12factor.net/logs).

---

## PY-050 — Module-level `logger = logging.getLogger(__name__)`

**What.** Every module that logs creates one module-level logger:

```python
# top of any module that logs
import logging

logger = logging.getLogger(__name__)
```

Never call `logging.info(...)`, `logging.error(...)` etc. directly
— those go to the root logger.

**Why.** Three reasons:

1. **`logging.info(...)` is unidentifiable.** It logs through the root logger with no module context — you can't tell from output which file emitted the message. With a module-level logger, `__name__` becomes the logger name (e.g. `mypackage.handlers.users`), and every output line includes that name.
2. **The root logger has no handlers by default** (or gets whatever `basicConfig` was called with). `logging.info("foo")` either drops the message silently or goes somewhere unexpected, depending on what was called before.
3. **Module-level loggers enable hierarchical filtering.** With `mypackage.handlers.users` as the logger name, you can set `[loggers]` config to silence `mypackage.handlers.*` to WARNING while keeping `mypackage.core.*` at INFO. Root-logger calls can't be filtered this way.

The `__name__` idiom is the Python convention. PyCharm, VS Code,
and every other linter knows it. Anything else is non-idiomatic.

**How.**

```python
# src/mypackage/handlers/users.py
import logging

logger = logging.getLogger(__name__)
# logger.name is "mypackage.handlers.users"

def create_user(name: str) -> User:
    logger.info("Creating user %s", name)
    ...
```

```python
# Never:
import logging

def create_user(name: str) -> User:
    logging.info("Creating user %s", name)   # root logger; bad
    ...
```

**When NOT to apply.** One-off scripts and `__main__.py` entry
points may call `logging.basicConfig(...)` + `logging.info(...)`
when the simplicity is worth more than the discipline. Library
code never does this; application module-level code never does
this. Only quick scripts.

---

## PY-051 — Positional args in log calls; never f-strings

**What.** Pass interpolation args as positional parameters:

```python
# RIGHT
logger.info("User %s logged in from %s", user_id, ip_address)

# WRONG — f-string
logger.info(f"User {user_id} logged in from {ip_address}")
```

The same rule applies to `.format()`, `%` formatting, and any other
form of pre-formatting the message string.

**Why.** Three concrete failures from f-strings in log calls:

1. **Interpolation cost is paid even when level is disabled.**
   `logger.debug(f"State: {expensive_compute()}")` calls
   `expensive_compute()` *every time*, even if the logger is set
   to INFO and DEBUG messages are discarded. With positional args,
   the interpolation only happens if the message is actually
   emitted.
2. **Sentry / log aggregator grouping breaks.** Sentry, Datadog,
   and similar tools group log events by the *message template*.
   With positional args, the template is `"User %s logged in from %s"`
   — one event with many occurrences. With f-strings, every distinct
   `user_id` produces a different message string, and the aggregator
   sees each as a unique event. You lose the ability to count "how
   many users logged in," and the issue list becomes useless.
3. **Pylint's `W1203` (logging-fstring-interpolation)** flags this
   automatically. Ignoring the warning is choosing to pay the costs
   above.

The performance and grouping costs together are significant in
production logging. For a high-volume application, this difference
is on the order of "log aggregator works" vs. "log aggregator is
overwhelmed by cardinality."

**How.**

```python
# Positional args — defers interpolation
logger.info("User %s logged in from %s", user_id, ip)

# For expensive args, also guard explicitly:
if logger.isEnabledFor(logging.DEBUG):
    logger.debug("Full state: %s", compute_debug_state())

# structlog uses kwargs by design — defers internally
import structlog
log = structlog.get_logger()
log.info("user_logged_in", user_id=user_id, ip=ip)
# emits: {"event": "user_logged_in", "user_id": 42, "ip": "1.2.3.4"}
```

The structlog idiom is **kwargs in log calls** for the same reason
positional args are correct for stdlib — structlog defers
rendering until the processor pipeline runs.

**When NOT to apply.** structlog's `log.info("msg", key=value)`
kwargs pattern is fine — structlog handles deferral internally,
and the kwargs *are* the structured fields, not interpolation
placeholders. The rule is "never f-strings"; structlog kwargs
aren't f-strings.

---

## PY-052 — Libraries add only `NullHandler`; never configure logging

**What.** A library's `__init__.py` (or top-level module) does
exactly one thing related to logging: register a `NullHandler` on
its own logger. Nothing else.

```python
# src/mylib/__init__.py
import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())
```

That's the entire logging setup. Never:

- `logging.basicConfig(...)`
- `logging.getLogger().addHandler(...)` (root logger)
- `logging.getLogger("mylib").setLevel(...)`
- `logging.getLogger("mylib").addHandler(StreamHandler(...))`

**Why.** Logging configuration is the *application's*
responsibility. A library that configures logging poisons every
application that imports it:

1. **`basicConfig` adds a handler to the root logger.** If the
   library is imported before the application configures logging,
   the library's basicConfig wins. The application's later
   `dictConfig` may or may not override (depending on
   `disable_existing_loggers` and timing). Result: duplicate output
   to stderr, or the application's preferred handlers don't run.
2. **Setting a level on the library's logger overrides the app's
   choice.** If `mylib` sets its logger to DEBUG, the application
   can't quiet it to WARNING without explicit overrides — and the
   user usually doesn't know to add them.
3. **Adding handlers in the library causes duplicate output.** The
   library's StreamHandler runs *and* the application's handlers
   run; every log line is duplicated.

`NullHandler` exists precisely for this: it's a no-op handler that
satisfies stdlib's "must have at least one handler or you get
'No handlers could be found' warnings on Python <3.2" rule, without
actually emitting anything. The application can then add real
handlers and control the library's output.

**How.**

```python
# src/mylib/__init__.py
"""mylib — public API."""
import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())

# Re-exports
from mylib.client import Client
__all__ = ["Client"]
```

Library code logs normally throughout:

```python
# src/mylib/client.py
import logging

logger = logging.getLogger(__name__)

class Client:
    def fetch(self, url: str) -> bytes:
        logger.info("Fetching %s", url)
        ...
```

Application configures everything (PY-053):

```python
# src/myapp/__main__.py
import logging.config

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    # ... handlers, formatters
    "loggers": {
        "mylib": {"level": "WARNING"},     # quiet the library
        "myapp": {"level": "DEBUG"},        # verbose for my own code
    },
}
logging.config.dictConfig(LOGGING)
```

**When NOT to apply.** Never. Even small utility libraries follow
this rule — the cost of compliance is one line of code; the cost
of violation can be hours of debugging "why is my log output
duplicated."

---

## PY-053 — Applications use `dictConfig` with `disable_existing_loggers: False`

**What.** Application entry points configure logging via
`logging.config.dictConfig(...)`. Always set
`disable_existing_loggers: False`.

```python
import logging.config

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,    # critical
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        },
    },
    "root": {"level": "INFO", "handlers": ["stdout"]},
    "loggers": {
        "mylib": {"level": "WARNING"},
        "uvicorn.access": {"level": "WARNING", "propagate": False},
    },
}

logging.config.dictConfig(LOGGING)
```

**Why.** Two failure modes:

1. **`disable_existing_loggers: True` (the legacy default)** silences any logger created before `dictConfig` ran — which is nearly every module-level logger in a typical app. The application starts up, configures logging, and then half the modules can no longer log because their loggers were created during import (before `dictConfig`).
2. **`basicConfig` is one-shot and limited.** It can configure exactly one handler on the root logger, with no per-logger level overrides. It's fine for a 50-line script; it's wrong for any real application.

`dictConfig` lets you:

- Configure multiple handlers (stdout for INFO, stderr for ERROR, file for audit).
- Set per-logger levels (`mylib` quieter than `myapp`).
- Use filters to add context or redact secrets (PY-055).
- Disable propagation on specific loggers (e.g. `uvicorn.access`
  to avoid duplicating access logs through the root handler).

**How.** Load the config dict from YAML/TOML for environment-specific
control:

```python
# src/myapp/logging_config.py
import logging.config
import yaml
from pathlib import Path

def configure_logging(env: str = "development") -> None:
    path = Path(__file__).parent / f"logging.{env}.yaml"
    config = yaml.safe_load(path.read_text())
    logging.config.dictConfig(config)
```

```yaml
# src/myapp/logging.production.yaml
version: 1
disable_existing_loggers: false
formatters:
  json:
    (): pythonjsonlogger.json.JsonFormatter
    fmt: "%(asctime)s %(name)s %(levelname)s %(message)s"
handlers:
  stdout:
    class: logging.StreamHandler
    stream: ext://sys.stdout
    formatter: json
root:
  level: INFO
  handlers: [stdout]
```

For early failure visibility, configure logging *before* anything
else in your `__main__.py`:

```python
# src/myapp/__main__.py
from myapp.logging_config import configure_logging
configure_logging()       # do this FIRST

from myapp.app import main   # imports happen after config
main()
```

**When NOT to apply.** One-off scripts where `logging.basicConfig(level=logging.INFO)`
is sufficient. The rule applies to applications with multiple
modules and any operational complexity.

---

## PY-054 — `logger.exception()` only inside `except`; `exc_info=True` elsewhere

**What.** Two related rules:

- `logger.exception("msg")` captures the current exception and traceback. Use it **only inside an `except` block** — it's shorthand for `logger.error("msg", exc_info=True)`.
- For logging exceptions stored elsewhere (caught in one function, logged in another), use `logger.error("msg", exc_info=the_exc)` explicitly.

```python
# RIGHT — inside except
try:
    risky_operation()
except ValueError:
    logger.exception("Risky operation failed")    # captures traceback

# RIGHT — error logging with full context
def handle_failure(exc: Exception):
    logger.error("Background task failed", exc_info=exc)

# WRONG — logger.exception() outside except block
logger.exception("Something happened")   # logs "NoneType: None" as the traceback
```

**Why.** Three failure modes:

1. **`logger.exception()` outside `except`** logs the literal string `NoneType: None` as the "traceback" — there is no current exception, so `sys.exc_info()` returns `(None, None, None)`. This is loud confusing noise; the message looks like an error but the "traceback" is meaningless.
2. **`logger.error("msg")` inside `except` without `exc_info`** logs the message *without the traceback*. The actual cause is invisible. This is the most common form of "we logged an error but I can't tell what went wrong" — the message says "Failed to do X" but the actual exception (`ConnectionRefusedError`? `JSONDecodeError`? `AssertionError`?) is lost.
3. **Bare `raise` in `except` after logging** logs the exception at the catch site *and* lets it propagate to be logged again at the framework level. Pick one: catch + log + handle, or let it propagate. Logging it twice produces duplicate stack traces in production logs.

**How.**

```python
import logging
logger = logging.getLogger(__name__)

# Pattern 1: catch, log, return graceful failure
try:
    result = call_external_api()
except RequestException:
    logger.exception("External API call failed")
    return None     # graceful degradation

# Pattern 2: catch, log, re-raise (avoid in most cases — let
# the framework log it if you can't add useful context)
try:
    result = call_external_api()
except RequestException as exc:
    logger.exception("External API call failed during user lookup")
    raise UserLookupError("Could not fetch user profile") from exc

# Pattern 3: log later (different scope)
async def background_worker():
    while True:
        try:
            await process_one()
        except Exception as exc:
            failures.append(exc)

def report_failures(failures: list[Exception]):
    for exc in failures:
        logger.error("Background job failed", exc_info=exc)
```

**When NOT to apply.** When you really just want a message without
a traceback — `logger.error("Custom check returned false")` is
fine. The rule says "include `exc_info` *when you intend to log an
exception*", not "always include `exc_info`."

---

## PY-055 — Context via `contextvars`; redact secrets at filter/formatter

**What.** Two patterns:

1. **Per-request context (request_id, user_id, trace_id) propagates via `contextvars`,** not function arguments. Inject into log records via a `logging.Filter` (stdlib) or `structlog.contextvars.bind_contextvars()` (structlog).
2. **Secret redaction happens at the filter or formatter level,** not at call sites. Don't trust developers to remember to redact tokens / passwords / keys at every log call.

**Why.** Two failure modes from getting either wrong:

**Without contextvars:** Either you pass `request_id` as a kwarg to
every function — error-prone, noisy, and breaks when one library
forgets — or you use thread-locals, which break under asyncio. Or
you stuff it into globals, which break under concurrency. contextvars
(PEP 567) is the modern answer: per-task / per-thread state with
proper async propagation.

**Without filter-level redaction:** A single `logger.info("Auth: %s", auth_header)`
that someone added to debug an issue and forgot to remove leaks
production credentials. Call-site redaction is impossible to audit
— you can't grep "did anyone log a password" because anyone *could
have* and the obligation was on them. Filter-level redaction is
*centralized*: every record passes through the filter, every log
output is sanitized regardless of what the call site did.

**How.** Context via contextvars:

```python
# src/myapp/context.py
from contextvars import ContextVar
request_id: ContextVar[str] = ContextVar("request_id", default="-")
user_id: ContextVar[str] = ContextVar("user_id", default="-")
```

```python
# Filter that injects contextvar values into every log record
import logging
from myapp.context import request_id, user_id

class ContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id.get()
        record.user_id = user_id.get()
        return True
```

```python
# dictConfig adds the filter to every handler
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "context": {"()": "myapp.logging.ContextFilter"},
    },
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(request_id)s/%(user_id)s] %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "filters": ["context"],
            "formatter": "default",
        },
    },
    "root": {"level": "INFO", "handlers": ["stdout"]},
}
```

structlog has a cleaner pattern for the same thing:

```python
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

# At request entry:
clear_contextvars()
bind_contextvars(request_id=req.id, user_id=req.user_id)

# All subsequent logger calls in this context automatically include those:
log = structlog.get_logger()
log.info("user_lookup", username="alice")
# → {"event": "user_lookup", "username": "alice", "request_id": "...", "user_id": "..."}
```

Redaction filter:

```python
import re
import logging

class RedactingFilter(logging.Filter):
    PATTERNS = [
        (re.compile(r'(password["\s:=]+)\S+', re.I), r'\1***'),
        (re.compile(r'(Bearer\s+)\S+'), r'\1***'),
        (re.compile(r'(api[-_]?key["\s:=]+)\S+', re.I), r'\1***'),
        (re.compile(r'(token["\s:=]+)\S+', re.I), r'\1***'),
        (re.compile(r'(secret["\s:=]+)\S+', re.I), r'\1***'),
    ]

    def filter(self, record):
        msg = record.getMessage()
        for pattern, replacement in self.PATTERNS:
            msg = pattern.sub(replacement, msg)
        record.msg = msg
        record.args = ()       # already interpolated; prevent re-interpolation
        return True
```

**When NOT to apply.** Internal dev tools and one-off scripts may
not need either pattern — the cost-benefit isn't there. The rule
applies to production-bound services where audit trails and
multi-tenant context propagation actually matter.

---

## PY-056 — Production: JSON to stdout, no in-process rotation, structlog for apps

**What.** Three intertwined recommendations for production logging:

1. **Output is JSON (or logfmt) to stdout.** No per-line text format; no in-process file rotation.
2. **No `RotatingFileHandler` / `TimedRotatingFileHandler`.** Let the container orchestrator (Docker, systemd, Kubernetes) handle log capture and rotation.
3. **Application code uses `structlog`; library code uses stdlib `logging`.**

```python
# Production logging config — structlog with JSON output to stdout
import logging
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
```

**Why.** Three failure modes from getting this wrong:

1. **In-process rotation breaks under multiprocessing and crashes.**
   `RotatingFileHandler` with multiple worker processes has file
   locking issues; you get truncated log files and lost messages.
   When the process is killed mid-rotate, the rotation is incomplete.
   Container orchestrators handle this correctly at the file-system
   level (Docker's logging driver, systemd's journal); doing it
   in-process duplicates effort and creates contention.
2. **Text logs are expensive in aggregators.** Loki, Datadog, and
   ELK can ingest unstructured text but every search costs more —
   the aggregator has to grep through the message body to find
   structured fields. With JSON, fields are pre-extracted; queries
   are O(1) on the field rather than O(text-length) on the line.
3. **stdlib `logging` is fine for libraries but underpowered for
   apps.** stdlib is the universal interop layer — every library
   uses it, and an application's `dictConfig` can capture all of
   it. But for application code, structlog adds: structured kwargs
   per call, easier context propagation (contextvars merge), a
   composable processor pipeline (redaction, sampling, enrichment),
   and ~2x throughput.

The full picture: stdlib `logging` is the *transport*, structlog
is the *application API* on top of it. Configure stdlib to capture
output from libraries, then structlog (which wraps stdlib) for
your own code. JSON-render at the end.

**How.** End-to-end production setup:

```python
# src/myapp/logging_config.py
import logging.config
import structlog
import sys

def configure_logging(level: str = "INFO") -> None:
    # stdlib config — captures library output, routes to stdout as JSON
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.processors.JSONRenderer(),
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "json",
            },
        },
        "root": {"level": level, "handlers": ["stdout"]},
    })

    # structlog config — application API
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

```python
# Application code uses structlog
import structlog
log = structlog.get_logger()

log.info("user_logged_in", user_id=42, ip="1.2.3.4")
# → {"event": "user_logged_in", "user_id": 42, "ip": "1.2.3.4",
#    "level": "info", "timestamp": "2026-05-26T10:00:00Z", "logger": "myapp.auth"}
```

```python
# Library code uses stdlib
import logging
logger = logging.getLogger(__name__)

logger.info("HTTP request: %s %s", method, url)
# → routed through the same stdlib handler, JSON-rendered the same way
```

For dev environments, swap `JSONRenderer` for
`structlog.dev.ConsoleRenderer()` to get pretty colored output.

**When NOT to apply.** Two cases:

1. **Libraries take stdlib only.** Don't take a structlog dependency in a library you publish.
2. **Single-user CLI tools.** The output goes to a terminal where humans read it; structured JSON to stdout is wrong because the terminal is the consumer, not a log aggregator. Use `structlog.dev.ConsoleRenderer` or stick with stdlib's text formatter.

Loguru is an alternate ergonomic library for application logging.
It has weaker stdlib interop (third-party library logs require a
custom sink bridge to flow through it), which makes it a worse
choice for production services that depend on many libraries.
Reasonable for solo scripts; structlog for team production code.

---

## PY-076 — Use `QueueHandler` / `QueueListener` for low-latency async logging

**What.** In services where logging happens on the request path —
async handlers, hot loops in batch jobs — wrap downstream handlers
in a [`QueueHandler`/`QueueListener`](https://docs.python.org/3/library/logging.handlers.html#queuehandler)
pair so the I/O happens off the request thread / event loop.

```python
# logging_config.py — 3.12+ shape
import logging
import logging.config

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
        },
    },
    "handlers": {
        # The real handler — synchronous I/O to stdout
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
        },
        # Queue-backed front-end; this is what loggers attach to
        "queue": {
            "class": "logging.handlers.QueueHandler",
            "handlers": ["stdout"],          # 3.12+: list resolved via getHandlerByName
            "respect_handler_level": True,
        },
    },
    "root": {"level": "INFO", "handlers": ["queue"]},
})

# Start the listener (drains the queue on a background thread).
# logging.config.dictConfig() does this automatically when the
# QueueHandler has `handlers: [...]` in 3.12+; for earlier
# versions, set up the QueueListener manually.
```

**Why.** Synchronous handler I/O is on the critical path of
whoever calls `logger.info(...)`:

1. **In async code, a slow handler blocks the event loop.** `logger.info()` calls the formatter, then the handler's `emit()` — which may write to stdout, a socket, a file. If stdout is being consumed by a slow sidecar (Fluent Bit, journald under load), the write blocks. The event loop stalls. Other requests queue up behind a log line. This is the same failure mode as PY-040, just with a more surprising trigger ("but it's only a log message").
2. **In threaded code, the GIL is held during `emit()`.** Same blocking story — every thread that wants to log waits behind the slow writer.
3. **Network handlers are the worst offender.** `SysLogHandler`, `HTTPHandler`, and `SocketHandler` synchronously open / send / wait on a socket inside `emit()`. A flaky log endpoint can take down request latency for the whole service.

`QueueHandler` decouples the producer (your code) from the
consumer (the actual I/O). Producer side: a thread-safe / async-safe
`put()` into a `queue.Queue`. Consumer side: `QueueListener` runs
on a dedicated background thread, dequeues records, and runs the
real handlers. If the downstream I/O slows down, the queue grows
but the request path stays fast.

Python 3.12 introduced
[`logging.getHandlerByName()`](https://docs.python.org/3/library/logging.html#logging.getHandlerByName),
which lets `dictConfig` resolve handler names inside a
`QueueHandler` config without manual wiring — the snippet above
uses that. On 3.11 and earlier, you have to construct the
`QueueHandler` / `QueueListener` pair programmatically.

Pair with PY-056: JSON-to-stdout remains the format and
destination; QueueHandler is the *transport* underneath that makes
it safe on the hot path.

**How.**

3.12+ — declarative `dictConfig` (handler resolution by name):

```python
import logging.config
import sys

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "pythonjsonlogger.json.JsonFormatter"},
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "json",
        },
        "queue": {
            "class": "logging.handlers.QueueHandler",
            "handlers": ["stdout"],
            "respect_handler_level": True,
        },
    },
    "root": {"level": "INFO", "handlers": ["queue"]},
})
```

Pre-3.12 — manual `QueueListener`:

```python
import logging
import logging.handlers
import queue
import sys

log_queue: queue.Queue = queue.Queue(-1)         # unbounded; bound it if you prefer to drop
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(JsonFormatter())

listener = logging.handlers.QueueListener(
    log_queue,
    stdout_handler,
    respect_handler_level=True,
)
listener.start()

# Use a QueueHandler as the only handler on the root logger
queue_handler = logging.handlers.QueueHandler(log_queue)
root = logging.getLogger()
root.addHandler(queue_handler)
root.setLevel(logging.INFO)

# At shutdown:
listener.stop()
```

If the queue is bounded (`queue.Queue(maxsize=N)`), the producer
blocks when full — same problem as synchronous I/O. Either use an
unbounded queue and trust the listener to drain it, or use a
bounded queue with `QueueHandler` subclassed to drop on overflow
(losing log records is sometimes preferable to blocking requests;
make the trade-off explicit).

**When NOT to apply.** Three cases:

1. **CLI tools and short-lived scripts.** Logging is synchronous to a terminal; the user *wants* it to flush before the process exits. The queue/listener pair adds a graceful-shutdown burden that earns nothing for a script that runs for 3 seconds.
2. **Tests.** pytest captures logging via `caplog`; introducing a queue between your code and the captor breaks the capture. Configure logging without QueueHandler in test config.
3. **Single-handler stdout logging with no slow sink behind it.** If you're confident the only downstream is an unblocked stdout pipe to a fast collector, the queue indirection is overhead with no upside. The rule fires when you have *any* network handler, file rotation, or slow consumer in the chain — which is most production services, but not all.
