# FAPI deployment rules

Detailed entries for `FAPI-090..FAPI-092`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[FastAPI deployment docs](https://fastapi.tiangolo.com/deployment/server-workers/),
[behind a proxy](https://fastapi.tiangolo.com/advanced/behind-a-proxy/),
and [CORS](https://fastapi.tiangolo.com/tutorial/cors/).

Container packaging itself (base image, non-root, `.dockerignore`) lives
in [`containers-best-practices`](../../containers-best-practices/SKILL.md).

---

## FAPI-090 — Run one Uvicorn process per container; let the orchestrator replicate

**What.** In Kubernetes or any container orchestrator, start the app with
a single process: `fastapi run app/main.py` or
`uvicorn app.main:app --host 0.0.0.0 --port 8000`. Prefer one process per
container and avoid `--workers N` or Gunicorn inside it; scale by running
more pods. (Workers-per-container is a valid model too, but it muddies the
per-pod accounting described below.)

**Why.** Multiple workers inside one container blur per-pod metrics (each
worker has its own memory, so the orchestrator's autoscaling signal is
muddied), complicate graceful rolling updates (the container must drain
every worker before replacement), and break one-to-one correlation of pod
logs with request traces. Pod replication is the orchestrator's job and
the right scaling primitive.

**How.**

```dockerfile
CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# k8s Deployment
spec:
  replicas: 4
```

**When NOT to apply.** A single VM or bare-metal host with no
orchestrator is the classic place for multiple workers — there
`uvicorn --workers N` (or Gunicorn managing Uvicorn workers) is the right
way to use all cores.

---

## FAPI-091 — Set `--forwarded-allow-ips` and `root_path` when running behind a proxy

**What.** Behind nginx, Traefik, or a cloud load balancer, start the
server with `--forwarded-allow-ips` set to the proxy's IP (or `"*"` when
the network already restricts who can reach the app) so forwarded
`X-Forwarded-*` headers are trusted. If the proxy strips a path prefix,
also set `root_path` (`--root-path /api/v1` or `FastAPI(root_path=...)`).

**Why.** Without trusting forwarded headers, `request.url.scheme` reports
`http` even when the client used HTTPS — breaking redirect URLs and
`Secure`-cookie logic. Without `root_path`, the `/docs` UI requests the
OpenAPI schema from the wrong path and 404s, so Swagger UI is unusable
through the proxy.

**How.**

```bash
fastapi run app/main.py --forwarded-allow-ips="203.0.113.0/24" --root-path /api/v1
```

Set `--forwarded-allow-ips` to specific proxy addresses rather than `"*"`
unless the app is unreachable except through the proxy.

**When NOT to apply.** An app exposed directly with no proxy in front
needs neither flag — and don't set `--forwarded-allow-ips="*"` on a
directly-reachable app, since then any client can spoof its source IP and
scheme.

---

## FAPI-092 — Never combine `allow_origins=["*"]` with `allow_credentials=True` in CORS

**What.** `CORSMiddleware` must not pair `allow_origins=["*"]` with
`allow_credentials=True`. In production, list explicit origins (from
config), not a wildcard.

**Why.** The CORS spec forbids wildcard-origin plus credentials precisely
because it would let any website make authenticated cross-origin requests
with the victim's cookies — a CSRF vector. Browsers block the
combination, but some middleware silently emits the bad headers rather
than erroring, so the misconfiguration ships and "works" until a browser
rejects it (or an attacker exploits a misimplementation).

**How.**

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],   # explicit, from config
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**When NOT to apply.** A genuinely public, unauthenticated, read-only API
can use `allow_origins=["*"]` — but only *without* `allow_credentials`,
since there are no credentials to protect.
