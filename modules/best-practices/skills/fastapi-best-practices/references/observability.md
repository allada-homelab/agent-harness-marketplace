# OBS observability rules

Detailed entries for `OBS-001`, `OBS-003..OBS-006`. Each follows the
four-part **What / Why / How / When NOT to apply** shape. (`OBS-002` is
reserved.)

Citations point at the
[Kubernetes probes docs](https://kubernetes.io/docs/concepts/workloads/pods/probes/),
the [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python)
and [OpenTelemetry specification](https://github.com/open-telemetry/opentelemetry-specification)
repositories, the
[semantic conventions](https://github.com/open-telemetry/semantic-conventions),
and [Starlette's middleware docs](https://github.com/Kludex/starlette/blob/1.7.0/docs/middleware.md).

---

## OBS-001 — `/healthz` is liveness (no dependency checks); `/readyz` is readiness (checks the database, 503 problem+json when it can't)

**What.** Serve two unauthenticated probes. `/healthz` returns 200
`{"status": "ok"}` and touches nothing. `/readyz` runs `SELECT 1` through
the pool with a 2 s timeout, and returns 200 `{"status": "ready"}` or a
503 problem+json naming the failure (`database unavailable:
<ExceptionType>`). The image's `HEALTHCHECK` probes `/healthz`.

**Why.** An orchestrator restarts a container that fails liveness and
stops routing traffic to one that fails readiness. If liveness checked
the database, an outage would restart every replica. That fixes nothing
and adds reconnect load just as the database recovers, a cascading
failure. Readiness checking the database takes out of rotation a replica
that could only return errors, and it comes back without a restart once
the database answers.
Source: https://kubernetes.io/docs/concepts/workloads/pods/probes/

> When your app has a strict dependency on back-end services, you can implement both a liveness and a readiness probe. The liveness probe passes when the app itself is healthy, but the readiness probe additionally checks that each required back-end service is available.

> Incorrect implementation of liveness probes can lead to cascading failures.

**How.**

```python
import asyncio

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}  # liveness: never touches a dependency


@router.get("/readyz", responses={503: {"description": "Not ready"}})
async def readyz(request: Request) -> JSONResponse:
    try:
        async with asyncio.timeout(2), request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # any failure means "not ready", not a 500
        return JSONResponse(
            {
                "type": "about:blank",
                "title": "Service Unavailable",
                "status": 503,
                "detail": f"database unavailable: {type(exc).__name__}",
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/problem+json",
        )
    return JSONResponse({"status": "ready"})
```

```dockerfile
# Liveness only; the image's own Python, no curl.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
```

**When NOT to apply.** Docker and Compose have a single healthcheck and
don't route by readiness, so there `/readyz` is informational (point the
Compose healthcheck at `/healthz`). Readiness only pays off behind a load
balancer or Kubernetes Service that honours it. At high probe rates,
every `/readyz` call is a database round trip, so keep the probe interval
sensible.

---

## OBS-003 — OTel API always instrumented; SDK/exporters only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set

**What.** A `from_environment()` factory returns the API's
`NoOpTracerProvider` / `NoOpMeterProvider` when
`OTEL_EXPORTER_OTLP_ENDPOINT` is unset or empty. When it's set, it builds
SDK providers: a `TracerProvider` with a
`BatchSpanProcessor(OTLPSpanExporter())`, a `MeterProvider` with a
`PeriodicExportingMetricReader(OTLPMetricExporter())`, and a `Resource`
that defaults `service.name` only when `OTEL_SERVICE_NAME` isn't set.
Either way the FastAPI and SQLAlchemy instrumentors run with those
providers, so the code path is the same with and without export. The
lifespan shuts the SDK providers down, which flushes buffered spans and
metrics.

**Why.** Instrumentation written against the API costs next to nothing
with no-op providers, so there's no second code path to keep in sync.
Gating the SDK on the endpoint means a developer's `pytest` or
`docker compose up` never tries to reach a collector that isn't there.
The exporters read the endpoint and service name from OTel's standard
variables, so a deployment configures them without app-specific
settings.
Sources: https://github.com/open-telemetry/opentelemetry-python/blob/v1.44.0/docs/api/index.rst,
https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/protocol/exporter.md,
https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/configuration/sdk-environment-variables.md

> The OpenTelemetry Python API provides the core interfaces and no-op implementations for instrumenting applications with traces, metrics, and logs.

> - Default:  `http://localhost:4318` [1]
> - Env vars: `OTEL_EXPORTER_OTLP_ENDPOINT` `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`

> If `service.name` is also provided in `OTEL_RESOURCE_ATTRIBUTES`, then `OTEL_SERVICE_NAME` takes precedence.

**How.**

```python
import os
from dataclasses import dataclass

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass(frozen=True)
class Telemetry:
    tracer_provider: trace.TracerProvider
    meter_provider: metrics.MeterProvider

    def shutdown(self) -> None:
        # SDK providers flush buffered spans/metrics; the no-op API providers have nothing to do.
        for provider in (self.tracer_provider, self.meter_provider):
            if isinstance(provider, TracerProvider | MeterProvider):
                provider.shutdown()


def from_environment() -> Telemetry:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return Telemetry(trace.NoOpTracerProvider(), metrics.NoOpMeterProvider())
    # Attributes passed to Resource.create override the environment's, so only
    # default the service name when OTEL_SERVICE_NAME isn't set.
    defaults = {} if os.environ.get("OTEL_SERVICE_NAME") else {"service.name": "myapp"}
    resource = Resource.create(defaults)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    return Telemetry(tracer_provider, meter_provider)


def instrument_app(app: FastAPI, telemetry: Telemetry) -> None:
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
        excluded_urls="healthz,readyz",  # probes would drown the real traffic
    )
```

Call `telemetry.shutdown()` in the lifespan's `finally` (FAPI-004), and
instrument the SQLAlchemy engine with the same providers
(`SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine,
tracer_provider=..., meter_provider=...)`) so an HTTP span and its SQL
spans share a trace id. Deploy with, for example,
`OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318`.

**When NOT to apply.** The spec gives `OTEL_EXPORTER_OTLP_ENDPOINT` a
default (`http://localhost:4318`), so "unset means off" is this app's
choice, not the spec's: a deployment that relies on a node-local
collector at that default must set the variable explicitly. The
providers are wired by hand rather than by `opentelemetry-instrument`
auto-configuration, so `OTEL_TRACES_EXPORTER` isn't honoured and of
`OTEL_METRICS_EXPORTER` only `none` is (OBS-005); `OTEL_SDK_DISABLED`
still works, because the SDK providers check it themselves. A library
should depend on the API alone and never start an SDK.

---

## OBS-004 — `X-Request-ID` reused if safe (else generated), echoed on every response, and stamped on every log line with the active `trace_id`/`span_id`

**What.** A `RequestIdMiddleware` (outermost, added last in the app
factory) reuses the caller's `X-Request-ID` when it matches
`[A-Za-z0-9._-]{1,64}`, otherwise generates `uuid4().hex`. It sets a
`request_id` ContextVar for the request, resets it afterwards, and adds
the id to the response headers. A logging filter copies it onto every
record together with the current span's `trace_id` (32 hex) and
`span_id` (16 hex), and the JSON formatter emits them.

**Why.** The request id lets a caller or support ticket point at one
request's log lines. The trace and span ids join those lines to the
trace in the tracing backend, which is how OpenTelemetry correlates logs
with traces. Validating the incoming id stops a caller from injecting
arbitrary text into logs and response headers.
Source: https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/logs/README.md

> This allows to directly correlate logs and traces that correspond to the same execution context.

**How.** The middleware (pure ASGI, see OBS-006):

```python
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# An incoming id is reused only if it's short and plain: it ends up in logs and response headers.
VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode())]
            await send(message)

        reset_token = request_id.set(rid)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id.reset(reset_token)
```

The filter that stamps every record:

```python
import logging

from opentelemetry import trace


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        context = trace.get_current_span().get_span_context()
        record.trace_id = format(context.trace_id, "032x") if context.is_valid else None
        record.span_id = format(context.span_id, "016x") if context.is_valid else None
        return True
```

Add the middleware last (`app.add_middleware(RequestIdMiddleware)` after
instrumenting the app) so it is outermost and every log line of the
request carries the id. If logging goes through a `QueueHandler`, attach
the filter to the queue handler so it runs in the request's task, where
the ContextVar and active span are still set.

**When NOT to apply.** Behind a gateway that already assigns the request
id, trust only the gateway's header and drop the client's. If every
consumer of the logs reads trace ids, the separate request id is
optional.

---

## OBS-005 — HTTP metrics as OTel metrics pushed over OTLP, on the stable `http.server.request.duration` (`OTEL_SEMCONV_STABILITY_OPT_IN=http`); `OTEL_METRICS_EXPORTER=none` turns them off

**What.** No `/metrics` scrape endpoint. With an endpoint configured
(OBS-003), a `MeterProvider` with a
`PeriodicExportingMetricReader(OTLPMetricExporter())` receives the
FastAPI and SQLAlchemy instrumentors' metrics. The image sets
`OTEL_SEMCONV_STABILITY_OPT_IN=http`, so the FastAPI instrumentation
records the stable `http.server.request.duration` histogram rather than
its older default names (set the same in the test configuration).
`OTEL_METRICS_EXPORTER=none` swaps in the no-op meter provider, for
example for a traces-only backend such as Jaeger, which takes OTLP
traces but answers OTLP metrics with 404.

**Why.** One OTLP endpoint carries traces and metrics to a collector, so
the app needs no extra port or scrape config, and the metric names
follow the stable semantic conventions that dashboards and backends
already know. Without the opt-in the instrumentation keeps emitting the
pre-stable names.
Sources: https://github.com/open-telemetry/semantic-conventions/blob/v1.44.0/docs/http/http-metrics.md,
https://github.com/open-telemetry/semantic-conventions/blob/v1.44.0/docs/non-normative/http-migration.md,
https://github.com/open-telemetry/opentelemetry-specification/blob/v1.61.0/specification/configuration/sdk-environment-variables.md

> `http.server.request.duration` | Histogram | `s` | Duration of HTTP server requests. | ![Stable](https://img.shields.io/badge/-stable-lightgreen)

> - `http` - emit the stable HTTP and networking conventions, and stop emitting the old HTTP and networking conventions that the instrumentation emitted previously.

> - The default behavior (in the absence of one of these values) is to continue emitting whatever version of the old HTTP and networking conventions the instrumentation was emitting previously.

> - `"none"`: No automatically configured exporter for metrics.

**How.** In the OBS-003 factory:

```python
meter_provider: metrics.MeterProvider = metrics.NoOpMeterProvider()
if os.environ.get("OTEL_METRICS_EXPORTER", "otlp") != "none":
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
```

And in the image:

```dockerfile
# Emit the stable HTTP semantic conventions (http.server.request.duration).
ENV OTEL_SEMCONV_STABILITY_OPT_IN=http
```

**When NOT to apply.** A Prometheus-only stack with no collector is
simpler with a pull `/metrics` endpoint (the spec's `prometheus`
exporter). Once the instrumentation's next major version emits only the
stable conventions, the opt-in variable is dead and can go.

---

## OBS-006 — Pure ASGI middleware, not Starlette's `BaseHTTPMiddleware`, for anything that sets a ContextVar (request id)

**What.** Middleware that sets a ContextVar — like OBS-004's
`RequestIdMiddleware` — is a plain ASGI class (`__init__(app)`,
`async __call__(scope, receive, send)`) that wraps `send` to add its
header, and passes non-HTTP scopes straight through.

**Why.** Starlette documents that `BaseHTTPMiddleware` stops ContextVar
changes propagating upward, and that one placed early in the stack
disrupts ContextVars for the pure ASGI middleware after it. The request
id lives in a ContextVar, so a `BaseHTTPMiddleware` anywhere in front of
the logging would break correlation. (A commonly repeated claim that
`BaseHTTPMiddleware` buffers and breaks streaming isn't in Starlette
1.7.0's documented limitations, so it isn't the reason recorded here.)
Source: https://github.com/Kludex/starlette/blob/1.7.0/docs/middleware.md

> Using `BaseHTTPMiddleware` will prevent changes to [`contextvars.ContextVar`](https://docs.python.org/3/library/contextvars.html#contextvars.ContextVar)s from propagating upwards.

> Importantly, this also means that if a `BaseHTTPMiddleware` is positioned earlier in the middleware stack, it will disrupt `contextvars` propagation for any subsequent Pure ASGI Middleware that relies on them.

**How.** The shape, stripped to its skeleton (OBS-004 has the full
request-id version):

```python
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class PureAsgiMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # lifespan, websocket: pass straight through
            await self.app(scope, receive, send)
            return

        async def wrapped_send(message: Message) -> None:
            await send(message)  # edit http.response.start headers here

        await self.app(scope, receive, wrapped_send)


app.add_middleware(PureAsgiMiddleware)
```

**When NOT to apply.** For a quick middleware that only reads the
request and touches no ContextVar, `@app.middleware("http")` is shorter
and fine.
