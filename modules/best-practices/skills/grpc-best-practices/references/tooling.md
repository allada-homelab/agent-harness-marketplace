# GRPC tooling rules

Detailed entries for `GRPC-014..GRPC-015`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GRPC-014 — Manage schemas with `buf`; gate CI on `buf lint` + `buf breaking --against`; keep generated code in sync

**What.** Author `.proto` in a buf workspace, enforce `buf lint` (style +
correctness rules), check breaking changes against a previous release with
`buf breaking --against`, and generate code with `buf generate` from a single
`buf.gen.yaml`. CI fails on lint, breaking, or generation drift (regenerate and
diff, or use generated-code verification).

**Why.** Schema drift and accidental breaking changes are the #1 compatibility
incident: field numbers reused (GRPC-001), enums renumbered, types changed —
all caught mechanically by `buf breaking` if it runs before publish, and
silently shipped if not. Hand-maintained per-service `protoc` Makefiles rot and
drift from each other; buf centralizes lint + generation as one reviewed
config.

**How.**

```yaml
# buf.yaml
version: v2
modules:
  - path: proto
lint:
  use: [STANDARD]
breaking:
  use: [FILE]
```

```bash
buf lint
buf breaking --against .git#tag=v0.1.0     # also usable: --against proto#branch=main
buf generate                               # outputs per buf.gen.yaml
```

**When NOT to apply.** Tiny internal-only schemas may relax breaking checks
between iterations (lint always pays). A working protoc setup shouldn't churn
for its own sake — the load-bearing requirements are (a) an enforced lint and
breaking gate and (b) deterministic generation; adopt buf incrementally when
the matrix of hand-rolled protoc commands grows.

---

## GRPC-015 — Enable server reflection in dev for grpcurl/grpcui; wire health checking (`grpc.health.v1`) for production probes

**What.** Servers open to tooling register the standard health service
(`grpc.health.v1`) and report serving status; in development also register
server reflection so `grpcurl`/`grpcui` can discover and call methods without
the `.proto` files.

**Why.** Health is what load balancers, Kubernetes liveness/readiness probes,
and meshes use to decide a pod can serve — gRPC has no connection-level "are
you ready?" signal, so the service must report it. Reflection is what makes
`grpcurl list <addr>` and API explorers work against an unfamiliar server — the
dev/onboarding experience that prevents blind integration. The two are often
conflated: reflection is dev ergonomics, health is production signal.

**How.**

```go
import (
    "google.golang.org/grpc/health"
    "google.golang.org/grpc/health/grpc_health_v1"
    "google.golang.org/grpc/reflection"
)

hs := health.NewServer()
hs.SetServingStatus("", grpc_health_v1.HealthCheckResponse_SERVING)
grpc_health_v1.RegisterHealthServer(s, hs)

if dev {
    reflection.Register(s)        // grpcurl list localhost:50051 works
}
```

Probe with the standalone binary (speaks the gRPC health protocol — unlike
`nc`/TCP checks a gRPC server can ignore):

```bash
grpc-health-probe -addr=:50051
```

**When NOT to apply.** Reflection on an internet-exposed production endpoint is
a metadata leak (method names and field shapes become discoverable) — gate it
behind an env flag or a non-public port. Health service is optional for
services nobody load-balances (CLI tools, batch jobs).
