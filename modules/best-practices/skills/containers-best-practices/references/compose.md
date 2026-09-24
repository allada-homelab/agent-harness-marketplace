# docker-compose rules

Detailed explanation for each `COMPOSE-NNN` rule.

Citations point at [the Compose Specification](https://docs.docker.com/compose/compose-file/)
and [Docker Compose CLI docs](https://docs.docker.com/compose/). The
Compose v2 spec has stabilized — when in doubt, verify against the spec
before claiming a property exists.

---

## COMPOSE-001 — Use `depends_on` with `condition: service_healthy`

**What.** When one service needs another to be *ready*, declare:

```yaml
depends_on:
  postgres:
    condition: service_healthy
```

Not the short form:

```yaml
depends_on:
  - postgres
```

**Why.** The short form only waits for the container to *start*, not for the
process inside to be ready. Real failure mode: web service comes up before
Postgres has finished initializing, fails its first connection, exits, and
the container goes into a restart loop. Or worse, the service starts but
hangs on the first query.

For this to work, the depended-on service needs a healthcheck (in the
compose file or its Dockerfile — see DOCKER-007 / COMPOSE-011).

**How.**

```yaml
services:
  postgres:
    image: postgres:16-alpine@sha256:...
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U postgres -d postgres"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 10s

  api:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
```

Pass `-h 127.0.0.1` to `pg_isready`. Without it, it probes the Unix
socket, and on first boot the official image runs a temporary setup
server that listens on the socket only (`listen_addresses=''` in its
`docker-entrypoint.sh`). The check can then pass before the real server
accepts TCP connections from `api`.

Available conditions: `service_started` (default short-form behavior),
`service_healthy` (preferred), `service_completed_successfully` (for one-shot
init containers).

Two more long-syntax keys:

- `restart: true` (Compose ≥2.17) — Compose restarts this service after it
  updates the dependency (e.g. the API restarts when `postgres` is recreated),
  so a stale connection pool does not outlive its database.
- `required: false` (Compose ≥2.20) — Compose only warns when the dependency
  isn't started or available, instead of failing; use it for a dependency that
  lives in an optional profile (COMPOSE-004).

```yaml
    depends_on:
      postgres:
        condition: service_healthy
        restart: true
      otel-collector:
        condition: service_started
        required: false
```

Cite: [compose reference — depends_on](https://docs.docker.com/reference/compose-file/services/#depends_on).

**When NOT to apply.** When the service can genuinely tolerate the
dependency being unavailable (and has retry/backoff). Even then, the
healthcheck-aware form makes startup faster and more predictable.

---

## COMPOSE-002 — Pick named volumes vs bind mounts deliberately

**What.** Two distinct mount types:

- **Named volume** — managed by Docker, lives in Docker's storage. `db_data:/var/lib/postgresql/data`.
- **Bind mount** — points at a host path. `./src:/app/src`.

Use named volumes for *Docker-managed state* (databases, package caches),
bind mounts for *developer-edited content* (source code, config files).

**Why.** Bind-mounting a database directory causes file-permission issues
(database UIDs don't match host UIDs), slow I/O on macOS/Windows (the file
sharing layer is slow), and accidental destruction (`rm -rf ./db_data` on
the host wipes the DB). Conversely, putting source code in a named volume
makes it invisible to the host editor.

**How.**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - db_data:/var/lib/postgresql/data   # named volume — managed state
      - ./db/init:/docker-entrypoint-initdb.d:ro  # bind mount — initialization scripts

  api:
    build: .
    volumes:
      - ./src:/app/src    # bind mount — live source for development
      - api_cache:/app/.cache  # named volume — internal cache

volumes:
  db_data:
  api_cache:
```

**When NOT to apply.** When you genuinely need to inspect database files
from the host (rare and usually a smell — use a DB client instead).

---

## COMPOSE-003 — Use `env_file` for secrets-adjacent values

**What.** Put environment variables in a separate file referenced via
`env_file`, especially anything secret or environment-dependent. Don't
inline them in `environment:`.

**Why.** Inline `environment:` values live in the checked-in `compose.yml`.
`env_file` references can point at a `.env` (gitignored) for secrets or
`.env.example` (committed) for documentation. This separates *what the
service needs* from *what the value is*.

**How.**

```yaml
services:
  api:
    build: .
    env_file:
      - .env                # gitignored, real values
      - .env.shared         # committed, shared defaults
    environment:
      LOG_LEVEL: info       # ok to inline if truly non-secret and stable
```

```
# .env.example (committed)
DATABASE_URL=postgres://postgres:postgres@postgres:5432/app
OPENAI_API_KEY=replace-me
```

```
# .env (gitignored, copied from .env.example by each contributor)
DATABASE_URL=postgres://postgres:postgres@postgres:5432/app
OPENAI_API_KEY=sk-real-value
```

**When NOT to apply.** Single-value, truly non-secret config can stay
inline — it reads better than indirection through a file. But `env_file`
scales better as the count grows.

---

## COMPOSE-004 — Gate optional services with `profiles`

**What.** Use `profiles:` to mark services that should only start in
specific scenarios — debug tools, monitoring, alternative backends.

**Why.** Without profiles, `docker compose up` starts everything, including
heavyweight optional services. Profiles let you have one `compose.yml` that
covers dev, debug, and full-stack scenarios without splitting into
override files for every variation.

**How.**

```yaml
services:
  api:
    build: .

  postgres:
    image: postgres:16-alpine

  redis:
    image: redis:7-alpine
    profiles: ["cache"]            # only starts with --profile cache

  jaeger:
    image: jaegertracing/all-in-one:latest
    profiles: ["debug"]            # only starts with --profile debug

  mailhog:
    image: mailhog/mailhog
    profiles: ["debug", "email"]   # in multiple profiles
```

```bash
docker compose up                          # api + postgres only
docker compose --profile debug up          # adds jaeger + mailhog
docker compose --profile cache --profile debug up   # everything
```

**When NOT to apply.** When the variations are large enough to deserve
their own `compose.override.yml` or `compose.prod.yml`. Profiles are for
small flavor-toggles within one logical environment.

---

## COMPOSE-005 — Commit `compose.override.yml` as the shared dev overlay

**What.** `compose.yml` (or `docker-compose.yml`) holds the canonical
config. `compose.override.yml` holds the shared *development* overlay
(build from source, published ports, debug settings) that a bare
`docker compose up` auto-loads on top of it. Commit both. Production and
other deployed environments name their files explicitly with `-f`, which
leaves the override out. Personal, per-developer tweaks go in a
gitignored file (e.g. `compose.local.yml`) passed with an extra `-f`.

**Why.** Without a committed dev overlay, contributors fork the base file
or pile dev settings into it, and those settings then ship to prod.
Gitignoring the override instead makes every contributor's dev stack
drift, and nothing in the repo describes how to run it. Docker's own
merge docs use the override for the dev configuration and deploy prod
with `-f`: "This deploys all three services using the configuration in
`compose.yaml` and `compose.prod.yaml` but not the dev configuration in
`compose.override.yaml`."
([Docker docs — Merge Compose files](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/))

**How.**

`compose.yml` (committed):

```yaml
services:
  api:
    build: .
    environment:
      LOG_LEVEL: info
```

`compose.override.yml` (committed; dev only):

```yaml
services:
  api:
    environment:
      LOG_LEVEL: debug
    ports:
      - "5678:5678"     # debugger port — dev only
```

```bash
docker compose up   # dev: automatically merges compose.override.yml on top
```

Deployed environments name their files explicitly, so the dev overlay is
never loaded:

```bash
docker compose -f compose.yml -f compose.prod.yml up -d
```

For personal tweaks, add a gitignored file and pass it on top of the
dev pair. Once you pass any `-f`, Compose stops auto-loading the
override, so list it too:

```bash
# .gitignore: compose.local.yml
docker compose -f compose.yml -f compose.override.yml -f compose.local.yml up
```

**When NOT to apply.** When the project has no dev-specific settings,
there is nothing to put in an override; don't create an empty one.

---

## COMPOSE-006 — Remove the top-level `version:` key

**What.** Compose v2 ignores the top-level `version:` key. Files starting
with `version: "3.8"` are still parsed, but the directive does nothing —
remove it for clarity.

**Why.** The `version:` key was meaningful in Compose v1 (Python). Compose
v2 (Go, the current implementation in `docker compose`) follows the
[Compose Specification](https://github.com/compose-spec/compose-spec), which
is unversioned. Leaving `version:` in causes warnings on newer Compose
versions and gives a false sense of pinning that does nothing.

**How.**

```yaml
# good
services:
  api:
    image: myapp:latest
```

```yaml
# stale — version: is ignored, remove it
version: "3.8"
services:
  api:
    image: myapp:latest
```

**When NOT to apply.** When you genuinely need backward compatibility with
the deprecated Python `docker-compose` v1 binary. That binary is end-of-life
— migrate instead.

---

## COMPOSE-007 — Define explicit networks for multi-service apps

**What.** Define named networks and assign services to them, rather than
relying entirely on the default bridge network.

**Why.** Explicit networks let you isolate service-to-service traffic
(e.g. `api` and `db` on a backend network, `nginx` and `api` on a frontend
network — `nginx` can't reach the DB directly). They also document
intended communication paths.

A named network only separates services from *each other*. Each one is
still an ordinary bridge with outbound internet access. To cut a backend
off from the outside, mark it `internal: true`
([compose networks — internal](https://docs.docker.com/reference/compose-file/networks/#internal)).
A service attached *only* to an internal network also loses its
published `ports:`. They bind, but the host can't reach them. So publish
ports only from services that also sit on a non-internal network.

**How.**

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    networks: [frontend]

  api:
    build: .
    networks: [frontend, backend]
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    networks: [backend]   # not reachable from nginx, no internet egress

networks:
  frontend:
  backend:
    internal: true
```

For simple two-service apps, the default network is fine — don't add
complexity until it earns its keep.

**When NOT to apply.** Single-service or trivial two-service compose files.
Explicit networking is worth the cost once you have ≥3 services or any
sensitive service that shouldn't be broadly reachable.

---

## COMPOSE-009 — Use `restart: unless-stopped` for long-lived services

**What.** Set `restart: unless-stopped` (not `always`, not `on-failure`,
not unset) for services that should survive container exits.

**Why.** Restart-policy tradeoffs:

- `no` (default) — container stays exited after a crash. Bad for long-lived dev services.
- `always` — restarts whenever the container exits. A manual stop is honored until the Docker daemon restarts; then the container comes back.
- `on-failure` — restarts only on non-zero exit. Misses cases where the process exits cleanly but shouldn't have.
- `unless-stopped` — identical to `always` except after a manual stop: the container stays stopped even across a daemon restart. Best default for "I want this running, but my `docker compose stop` should stick."

The *only* difference between `always` and `unless-stopped` is that
daemon-restart case — both honor a manual stop while the daemon keeps
running. `always` fits a service that must come back after a host reboot
even if someone stopped it by hand.

Cite: [Start containers automatically](https://docs.docker.com/engine/containers/start-containers-automatically/),
[compose reference — restart](https://docs.docker.com/reference/compose-file/services/#restart).

**How.**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped

  api:
    build: .
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
```

**When NOT to apply.** One-shot containers (migrations, seed scripts,
batch jobs) — use `restart: no` and let the orchestrator (or `docker
compose run`) handle them.

---

## COMPOSE-010 — Use YAML anchors / `extends` instead of duplicating service definitions

**What.** When multiple services share configuration (the same base image,
the same env vars, the same restart policy), extract a YAML anchor or use
`extends:`.

Note that `extends:` merges a *single service* definition from another
file into the current one — it's service-level reuse. That's distinct
from `include:` (COMPOSE-019), which loads a *whole sub-application*
(its own services, networks, volumes, configs) into the current
project. Use `extends:` to deduplicate a service block; use `include:`
to compose multiple compose files into one project.

**Why.** Copy-paste service definitions drift. A change to the base image
of one service gets forgotten on the other. Anchors and `extends` give one
canonical source.

**How.** YAML anchors (works for any field):

```yaml
x-defaults: &defaults
  restart: unless-stopped
  env_file: [.env]
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"

services:
  api:
    <<: *defaults
    build: .

  worker:
    <<: *defaults
    build: .
    command: ["python", "-m", "src.worker"]
```

`extends:` (more verbose, but more explicit about what's being inherited):

```yaml
services:
  api:
    extends:
      file: compose.base.yml
      service: app-base
```

**When NOT to apply.** Two-service compose files with little overlap —
anchors are over-engineering. Use them when duplication actually exists.

---

## COMPOSE-011 — Healthchecks belong on the services that need to be waited on

**What.** If service A `depends_on: B (condition: service_healthy)`, then
B must define a healthcheck (either in its Dockerfile or in the compose
file). Don't put a healthcheck on A and expect it to influence B.

**Why.** The dependency direction matters. The whole point of healthchecks
in compose is to gate startup ordering. Putting a healthcheck on the
*depending* service does nothing for ordering — though it can still be
useful for orchestrator restart logic.

**How.**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    healthcheck:                          # ← healthcheck on the dependency
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U postgres -d postgres"]
      interval: 5s
      retries: 10

  api:
    build: .
    depends_on:
      postgres:
        condition: service_healthy        # ← waiter references it
```

Common pitfall: relying on `HEALTHCHECK` from a third-party image without
checking what it actually does. Postgres's official image, for example,
ships *without* a healthcheck — you need to add one in compose.

**When NOT to apply.** When the waiter has its own robust retry/backoff
and doesn't need startup gating. Even then, healthchecks give better
visibility (`docker compose ps` shows healthy/unhealthy state).

---

## COMPOSE-012 — Use `service_completed_successfully` for one-shot init containers

**What.** For services that run once and exit (migrations, schema setup,
data seeding, config generation), use `restart: "no"` and gate downstream
services with `condition: service_completed_successfully`.

**Why.** Init containers don't fit the healthcheck model — they don't
have a "healthy" steady state, they just need to *finish*.
`service_completed_successfully` blocks dependent services until the init
container exits 0. Real failure mode without this pattern: the API
service starts before migrations have run, fails on a missing column,
restarts, fails again, eventually succeeds when the *separate* migration
job happens to finish — masking real ordering bugs.

**How.**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U postgres -d postgres"]
      interval: 5s
      retries: 10

  migrate:
    build: .
    restart: "no"                                # one-shot — don't restart
    command: ["alembic", "upgrade", "head"]
    depends_on:
      postgres:
        condition: service_healthy

  api:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully   # waits for migrate to exit 0
```

**The init container re-runs on every `up` — make it idempotent.**
Compose only *recreates* a container when its config changed,
`--force-recreate` was passed, or it was removed — but a plain
`docker compose up` still *starts* an existing `Exited (0)` one-shot
container again, so the migration or seed script executes on every run
(observed with Compose v5.5.1: two consecutive no-op `up -d` runs logged
the one-shot command twice). `restart: "no"` only stops the daemon from
restarting it after it exits; it does not stop `up` from starting it.
The operation must therefore be idempotent: `alembic upgrade head`
is; a seed script must use upserts or check for existing rows.

Cite: [compose reference — depends_on](https://docs.docker.com/reference/compose-file/services/#depends_on),
[compose up](https://docs.docker.com/reference/cli/docker/compose/up/).

**When NOT to apply.** Services that *do* run long enough to have a
meaningful healthy state — use `service_healthy` (COMPOSE-001) for those.
Truly background sidecars use `service_started`.

---

## COMPOSE-013 — Postgres: mount the data volume at the path for your major version

**What.** The official `postgres` image changed its data layout in 18:

- **Postgres ≤17** — `PGDATA` is `/var/lib/postgresql/data` and the image
  declares `VOLUME /var/lib/postgresql/data`. Mount the volume **there**,
  not at `/var/lib/postgresql`.
- **Postgres 18+** — `PGDATA` is version-qualified
  (`/var/lib/postgresql/18/docker`) and the `VOLUME` moved to
  `/var/lib/postgresql`. Mount the volume at `/var/lib/postgresql`.

**Why.** Mounting at the wrong level loses data silently. On ≤17, a
volume at `/var/lib/postgresql` leaves the image's `VOLUME` path
unmounted, so the runtime creates an *anonymous* volume there, the data
is written to it, and it is not reused when the container is re-created —
the image docs: mounts at the parent path "WILL NOT PERSIST database data
when the container is re-created." On 18+, a volume at the old
`/var/lib/postgresql/data` path misses the new `PGDATA` the same way. The
18+ layout also keeps one major version per subdirectory, so `pg_upgrade
--link` works across majors on the same volume.

**How.** Postgres ≤17:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    volumes:
      - app-db-data:/var/lib/postgresql/data       # ≤17: the image's VOLUME path
    secrets:
      - postgres_password
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U postgres -d postgres"]
      interval: 5s
      retries: 10

volumes:
  app-db-data:

secrets:
  postgres_password:
    environment: POSTGRES_PASSWORD
```

Postgres 18+:

```yaml
postgres:
  image: postgres:18-alpine
  # PGDATA defaults to /var/lib/postgresql/18/docker — no override needed
  volumes:
    - app-db-data:/var/lib/postgresql       # mount one level above the version dir
```

A `PGDATA` *subdirectory* of the mount (e.g. `.../data/pgdata`) is only
needed when the mount point itself is unusable as a data directory — a
filesystem root containing `lost+found`, or a host path whose ownership
the `postgres` user can't take — because `initdb` refuses a non-empty or
foreign-owned directory. A fresh named volume needs no subdirectory.

Upgrading 17 → 18 on an existing volume is a data migration, not a tag
bump: move the files into the `<major>/docker` layout (or `pg_upgrade`)
first, as the image docs describe.

Cite: [postgres image docs — PGDATA](https://github.com/docker-library/docs/blob/master/postgres/content.md#pgdata).

**When NOT to apply.** Other databases — MySQL, MariaDB, MongoDB have
their own `VOLUME` paths; check the image's docs for the equivalent.

---

## COMPOSE-014 — Use a local-only healthcheck endpoint for reverse proxies

**What.** A reverse proxy's healthcheck should hit a path the proxy
itself answers (e.g. nginx `location = /__healthz { return 200; }`), not
a path that proxies through to an upstream.

**Note on status.** This is a **community-recommended pattern**, not
explicit Docker / nginx documentation guidance. The strongest evidence
that it's the right approach: Traefik ships a purpose-built
[`/ping` endpoint](https://doc.traefik.io/traefik/operations/ping/) for
exactly this use, Envoy ships [`/ready`](https://www.envoyproxy.io/docs/envoy/latest/operations/admin#get--ready)
on its admin port for the same reason, and HAProxy has stats-page
liveness. The proxy projects designed first-class endpoints to support
this pattern — so it's *de facto* official even when not labeled as
such.

**Why.** If the proxy's healthcheck proxies to the backend, then *backend*
slowness or downtime fails the *proxy* healthcheck — the proxy gets
restarted, drops its connection pool, and amplifies the original
incident. The proxy itself is fine; you just punished it for a problem
it can't fix.

**How.** nginx side (in the config file or `configs:` block):

```nginx
location = /__proxy_healthz {
    access_log off;          # keep healthcheck noise out of logs
    return 200 "ok\n";
}
```

Compose side — but `nginx:*-alpine` does **not** ship `wget` or `curl`,
so the healthcheck `test:` needs a probe that's actually installed:

```yaml
services:
  proxy:
    image: nginx:1.27-alpine
    # nginx alpine has no wget/curl — use a tiny inline probe via /dev/tcp + nc
    # ... or install curl in your own image build:
    #   FROM nginx:1.27-alpine
    #   RUN apk add --no-cache curl
    healthcheck:
      test:
        - CMD-SHELL
        - >-
          wget -q --spider http://127.0.0.1/__proxy_healthz ||
          curl -fsS http://127.0.0.1/__proxy_healthz ||
          exit 1
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
```

The portable approach is to `apk add --no-cache curl` (≈10 KB on alpine)
in your own derived image and use the curl-only form:

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -fsS http://127.0.0.1/__proxy_healthz || exit 1"]
```

For Traefik / Envoy, use their built-in endpoints — no shell probe
needed:

```yaml
# Traefik
traefik:
  command: ["--ping=true"]
  healthcheck:
    test: ["CMD", "traefik", "healthcheck", "--ping"]

# Envoy
envoy:
  healthcheck:
    test: ["CMD", "curl", "-fsS", "http://127.0.0.1:9901/ready"]
```

Two extras worth noting:

- `access_log off` keeps the healthcheck out of access logs (saves disk + signal-to-noise).
- Use a path obscure enough to not collide with the app (`/__proxy_healthz`, not `/health`).

**When NOT to apply.** When you *want* to detect upstream-coupling at the
proxy layer (rare — usually that's a separate observability concern).
Then make sure the proxy's restart behavior won't make things worse.

---

## COMPOSE-015 — Use `develop.watch` for hot-reload, not bare bind mounts

**What.** Compose ≥ 2.22 ships a [`develop.watch`](https://docs.docker.com/compose/how-tos/file-watch/)
mechanism that watches host files and, on change, performs an action
(`sync`, `rebuild`, `restart`, `sync+restart`, or `sync+exec`) inside the container. Use it for
hot-reload during `docker compose watch` instead of bind-mounting the
entire workspace.

**Why.** Bare bind mounts work but have three problems for dev:

1. **Performance** — every host file event triggers an inotify event inside the container, which most tools handle inefficiently when the workspace contains build artifacts (`.venv/`, `node_modules/`).
2. **Granularity** — bind mounts give you "everything or nothing." `develop.watch` lets you say "sync `src/` to `/app/src/` but *rebuild* when `pyproject.toml` changes" — different actions for different paths.
3. **Platform performance** — on macOS/Windows, bind mounts go through the file-sharing layer (slow). `develop.watch` does selective sync via Compose's own mechanism — faster cold-start, fewer host events.

**How.**

```yaml
services:
  api:
    build: .
    develop:
      watch:
        # Sync source changes immediately
        - action: sync
          path: ./src
          target: /app/src
          ignore:
            - "**/__pycache__/**"
            - "**/.pytest_cache/**"

        # Rebuild when dependency manifests change
        - action: rebuild
          path: ./pyproject.toml
        - action: rebuild
          path: ./uv.lock

        # Sync + restart for config changes that need a reload
        - action: sync+restart
          path: ./config
          target: /app/config
```

Run with:

```bash
docker compose watch
```

Cite: [compose file-watch how-to](https://docs.docker.com/compose/how-tos/file-watch/).

The actions:

- **`sync`** — copy file changes into the running container. No restart. Use for source files when the app handles its own hot-reload (uvicorn `--reload`, vite, nodemon).
- **`rebuild`** — full image rebuild + container recreate. Use for manifests / Dockerfile changes.
- **`restart`** (Compose ≥2.32) — restart the container without syncing; for a bind-mounted or image-baked file whose change needs a process restart.
- **`sync+restart`** (Compose ≥2.23) — sync the file, then restart the container. Use when the app *doesn't* hot-reload and a config change requires a clean restart.
- **`sync+exec`** (Compose ≥2.32) — sync, then run the rule's `exec.command` inside the container (e.g. send the app a reload signal or regenerate an asset) without restarting it.

`initial_sync: true` on a `sync+*` rule syncs the path when the watch
session starts, so files changed while watch was stopped are not stale in
the container.

```yaml
        - action: sync+exec
          path: ./templates
          target: /app/templates
          initial_sync: true
          exec:
            command: ["kill", "-HUP", "1"]
```

Cite: [compose-file develop — watch](https://docs.docker.com/reference/compose-file/develop/#watch).

**When NOT to apply.** When the app has no hot-reload mode and rebuild
times are short — a plain `docker compose up --build` may be simpler.
When you need bidirectional sync (`develop.watch` is host → container
only).

---

## COMPOSE-016 — Use the `configs:` block for non-secret configuration files

**What.** The top-level `configs:` block mounts files into containers
the same way `secrets:` does — read-only, at a defined path — but for
*non-secret* config (nginx configs, prometheus configs, env-derived
templates, JSON/YAML feature flags).

**Why.** Three reasons to prefer `configs:` over alternatives:

1. **Versus bind mount.** A bind mount of a single file fails if the file doesn't exist (creates a directory in its place — see also DEVC's bind-mount pitfall). `configs:` has well-defined "this file must exist" semantics.
2. **Versus baking into the image.** Lets you swap the config without rebuilding. Useful for tuning nginx, swapping prometheus rules, A/B-ing feature flags.
3. **Versus env vars.** Some apps want a real file (nginx, postgres, java apps with `-Dconfig.file=`). `configs:` is the cleanest way to deliver it.

**How.**

```yaml
services:
  proxy:
    image: nginx:1.27-alpine
    configs:
      - source: nginx_conf
        target: /etc/nginx/conf.d/default.conf
        mode: 0444    # read-only for everyone
    ports: ["80:80"]

  prometheus:
    image: prom/prometheus
    configs:
      - source: prom_conf
        target: /etc/prometheus/prometheus.yml

configs:
  nginx_conf:
    file: ./nginx/default.conf

  prom_conf:
    # Inline content (small configs)
    content: |
      global:
        scrape_interval: 15s
      scrape_configs:
        - job_name: 'app'
          static_configs:
            - targets: ['api:8080']
```

Cite: [compose-file/configs](https://docs.docker.com/reference/compose-file/configs/).

Sources:

- **`file: ./path`** — read from a host file path.
- **`content: |\n ...`** — inline content (good for small configs that fit in compose.yml).
- **`environment: VAR`** — read content from a compose env var.
- **`external: true`** — reference a Docker / Swarm config managed outside Compose.

The official nginx image's [envsubst pattern](https://hub.docker.com/_/nginx)
combines `configs:` (or a mount at `/etc/nginx/templates/*.template`)
with the `NGINX_ENVSUBST_TEMPLATE_*` env vars to substitute env
variables at container start — useful when one config needs per-service
parameterization.

**When NOT to apply.** For secrets, use `secrets:` (SEC-009), not
`configs:` — the latter doesn't have the same "don't leak via inspect"
semantics. For huge config files (multi-MB), bind-mount or bake into
image instead — `content:` strings inflate the compose file itself.

---

## COMPOSE-017 — Set `pull_policy` explicitly for shared / production stacks

**What.** Compose's `pull_policy` controls when (or whether) Compose
pulls a service's image before starting it. Default is
`pull_policy: missing` (pull only if not present locally). Set it
explicitly when defaults bite you.

**Why.** Two real failure modes from leaving it at default:

1. **Stale tag** — you push a new `myimage:1.4` (or `:dev`, `:main`) to the registry, but a dev machine already has that tag cached locally. `compose up` doesn't pull; the dev runs old code and reports phantom bugs. (`latest` is the one tag Compose re-pulls even under `missing`.)
2. **Build vs pull confusion** — a service with both `image:` and `build:` defaults to pulling first, then falling back to build on failure. This isn't always what you want.

**How.**

```yaml
services:
  # Production: always pull the latest image at compose up
  api:
    image: ghcr.io/myorg/api:${API_TAG:-latest}
    pull_policy: always

  # Dev: always build locally, never pull (even if a registry image exists)
  worker:
    build: .
    image: myorg/worker:dev   # name for local cache
    pull_policy: build

  # Pinned-digest production: pull only if not present (default-ish, explicit)
  db:
    image: postgres:16-alpine@sha256:...
    pull_policy: missing
```

Cite: [compose-file pull_policy](https://docs.docker.com/reference/compose-file/services/#pull_policy).

Valid values:

| Value | Behavior |
|---|---|
| `always` | Pull every `compose up`. Slowest but most up-to-date. Best for prod with mutable tags. |
| `missing` (default) | Pull only if not present locally — except the `latest` tag, which is always pulled even under `missing`. |
| `never` | Never pull. Build-only or strictly-local. |
| `build` | Always build (ignores existing local image, forces rebuild). Useful for dev. |
| `if_not_present` | Synonym for `missing`. |
| `daily`, `weekly`, `every_<duration>` | Pull if the last pull is older than the period (e.g. `every_12h`). A middle ground between `always` and `missing` for mutable non-`latest` tags. |

**When NOT to apply.** When you've pinned every service by digest
(SEC-010) — pulling is then a content-addressed no-op for cached
images, and `pull_policy` has no practical effect. Default `missing` is
fine.

---

## COMPOSE-018 — Know the `--env-file` and `.env` precedence

**What.** Compose has *two* unrelated `.env` mechanisms, and confusing
them is a common source of "why isn't my variable picked up" debugging:

1. **`.env` in the project directory** — substituted into the compose file at *parse time* (`${VAR}` in compose.yml). Auto-loaded.
2. **`env_file:` in a service** — read by the *container* at runtime, into the service's environment. Not used for compose-file substitution.

`--env-file FILE` (on the `docker compose` command line) changes which
file feeds mechanism #1.

**Why.** Three real footguns:

1. **`.env` is parse-time, not runtime.** If a value is in `.env` but not referenced as `${VAR}` in compose.yml and not in any `env_file:`, the container won't see it. People expect `.env` to "just be there" inside containers.
2. **`--env-file` doesn't help containers.** It only changes the file used for compose-file substitution. Pass `env_file:` on the service to get values into the container.
3. **Variable precedence** is not what most people guess. Highest to lowest:
   1. Variables set in the shell (`export FOO=bar; docker compose up`).
   2. `--env-file FILE` on the command line.
   3. `.env` file in the project directory.

**How.** Make the layering explicit:

```yaml
# compose.yml
services:
  api:
    build: .
    # env_file: containers see these as env vars
    env_file:
      - .env.shared      # committed, defaults
      - .env             # gitignored, local overrides
    # environment: per-service overrides on top of env_file
    environment:
      LOG_LEVEL: ${LOG_LEVEL:-info}    # parse-time substitution from .env
```

For different environments, separate files and load explicitly:

```bash
# Local dev
docker compose up

# Staging — compose-file substitution from .env.staging
docker compose --env-file .env.staging up

# Production — set vars in shell (CI), don't ship .env
LOG_LEVEL=warn DATABASE_URL=... docker compose up
```

Cite: [compose env-file docs](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/).

**Two-file convention that works:**

- `.env.example` — committed. Documents every variable the stack needs (`DATABASE_URL=postgres://user:pass@db:5432/app`). Copied on first clone.
- `.env` — gitignored. Real values for local dev. Created from `.env.example`.

**When NOT to apply.** Single-environment setups where one `.env` file
serves all uses — there's nothing to disambiguate. Even then, naming
files explicitly (`.env.example`) helps onboarding.

---

## COMPOSE-023 — Set `security_opt: ["no-new-privileges:true"]` on production services

**What.** Add the `no-new-privileges` security option to every service
that doesn't have a documented reason to drop it:

```yaml
services:
  api:
    security_opt:
      - "no-new-privileges:true"
```

This sets the kernel's `PR_SET_NO_NEW_PRIVS` bit on the container's
processes, preventing any child process from acquiring elevated
privileges via `setuid` binaries, file capabilities, or
LSM-granted transitions.

**Why.** Without `no-new-privileges`, a process inside the container
that finds a `setuid` root binary on its filesystem can execute it and
gain root — even if the container was started as a non-root user
(DOCKER-005). The base images you build on contain a handful of
`setuid` binaries by default (`su`, `passwd`, `mount` on Debian; `su`,
`passwd` on Alpine). An attacker who lands code execution as the
unprivileged container user can bootstrap to UID 0 inside the
container, then look for kernel escape primitives.

`no-new-privileges` closes that path with zero functional cost for the
overwhelming majority of services — most containers never legitimately
need `setuid` transitions at runtime. It's also the foundation
Kubernetes' `securityContext.allowPrivilegeEscalation: false` relies
on; compose-level setups should match that posture.

A useful mental model: this is the "lock the door even though you also
have an alarm" rule. DOCKER-005 (non-root user) is the alarm;
`no-new-privileges` is the deadbolt. The combination is much stronger
than either alone, because together they make in-container privilege
escalation require an actual kernel vulnerability rather than a
misconfiguration.

**How.**

```yaml
services:
  api:
    image: ghcr.io/myorg/myapp@sha256:...
    user: "10001:10001"           # DOCKER-005 — non-root
    security_opt:
      - "no-new-privileges:true"  # COMPOSE-023 — can't escalate even if setuid is reachable
    cap_drop:
      - ALL                        # related — drop all caps then add back what's needed
    read_only: true                # related — read-only rootfs
    tmpfs:
      - /tmp
```

For a YAML anchor that propagates the safe defaults to every service:

```yaml
x-secure-defaults: &secure-defaults
  security_opt:
    - "no-new-privileges:true"
  cap_drop:
    - ALL

services:
  api:
    <<: *secure-defaults
    image: ghcr.io/myorg/myapp
    user: "10001:10001"
  worker:
    <<: *secure-defaults
    image: ghcr.io/myorg/myapp
    command: ["worker"]
    user: "10001:10001"
```

Note the syntax: `security_opt` is a list of strings, and the colon
between key and value (`no-new-privileges:true`) is part of the
string — *not* YAML key:value. Quote the whole entry to keep the YAML
parser from getting clever.

**When NOT to apply.** Two real cases:

1. **Services that genuinely need `setuid` transitions at runtime.** Rare — usually only true for containers running traditional Unix daemons that drop privileges via `setuid` (some legacy MTAs, certain sshd configurations). If you don't know whether your service needs it, it almost certainly doesn't.
2. **Dev containers that run `sudo` interactively.** A devcontainer where the human user invokes `sudo` from a shell needs privilege escalation to work. Omit `no-new-privileges` *only* for dev containers; never for production services.

In both cases, leave a comment in the compose file explaining the
exception so the next reviewer doesn't "fix" it back.

---

## COMPOSE-026 — Configure `logging:` with size + rotation on long-lived services

**What.** Production services should declare an explicit logging
configuration that bounds disk usage:

```yaml
services:
  api:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

Without this, the default `json-file` driver writes container stdout /
stderr to `/var/lib/docker/containers/<id>/<id>-json.log` with **no
size limit and no rotation**. A chatty service running for weeks can
quietly fill the host disk.

**Why.** Three concrete failure modes:

1. **Disk exhaustion takes down the host.** The default json-file log grows forever. A service emitting 1MB/min of access logs hits 1.5GB in a day and 45GB in a month. When `/var/lib/docker` fills, every container on the host degrades — not just the noisy one. Docker daemon itself starts failing, `docker ps` hangs, container restarts loop.
2. **`docker logs` becomes useless.** Without rotation, the log file can be tens of GB. `docker logs <container>` tries to seek through it; depending on the flags, it can stall the daemon for minutes. `docker logs --tail=100` works, but `docker logs` (full dump) is a footgun.
3. **Default-host configuration is *technically* possible but rarely deployed.** You can set rotation defaults in `/etc/docker/daemon.json` (`"log-opts": { "max-size": "10m", "max-file": "3" }`), but most production hosts don't, especially in mixed environments (compose-on-VM, ephemeral CI runners). Per-service `logging:` ensures the bound exists regardless of host config.

The trap is that the failure is **silent until catastrophic**: the
disk fills slowly, monitoring on `df` lags, and the first symptom is
an unrelated container failing to start because the daemon can't write
its own state. Setting `logging:` explicitly is the cheapest possible
fix.

**How.** Docker [recommends the `local` driver](https://docs.docker.com/engine/logging/configure/)
over `json-file`: it rotates by default and uses a more compact format
(`json-file` stays the default only for backwards compatibility). Prefer
it unless a tool reads the JSON log files directly:

```yaml
services:
  api:
    logging:
      driver: local
      options:
        max-size: "10m"
        max-file: "3"
```

If you stay on `json-file`, bound it explicitly — 10MB × 3 files =
30MB max per container, with the most recent 10MB always immediately
available:

```yaml
services:
  api:
    image: ghcr.io/myorg/myapp@sha256:...
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

For chatty access-log services, bump the per-file size but keep file
count modest:

```yaml
services:
  edge-proxy:
    image: nginx
    logging:
      driver: json-file
      options:
        max-size: "100m"
        max-file: "5"
        compress: "true"        # gzip rotated files
```

For very low-volume services where you want longer retention:

```yaml
services:
  scheduler:
    logging:
      driver: json-file
      options:
        max-size: "1m"
        max-file: "20"          # 20MB total, ~weeks of retention at low volume
```

Use a YAML anchor to avoid repeating the block on every service:

```yaml
x-log-defaults: &log-defaults
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"

services:
  api:
    <<: *log-defaults
    image: ghcr.io/myorg/myapp
  worker:
    <<: *log-defaults
    image: ghcr.io/myorg/myapp
    command: ["worker"]
```

If you're shipping logs to a centralized aggregator (Loki, ELK,
Datadog, CloudWatch), switch the driver — and still bound disk on
the local buffer:

```yaml
services:
  api:
    logging:
      driver: journald        # or: fluentd, gelf, awslogs, splunk
      options:
        tag: "myapp.{{.Name}}"
```

With a remote driver, `docker logs` keeps working on Docker Engine ≥20.10
through [dual logging](https://docs.docker.com/engine/logging/dual-logging/):
the daemon keeps a local-driver cache of recent output for every
container regardless of the configured driver (unless disabled with
`cache-disabled`). The cache is bounded, so it is not a substitute for
the aggregator during incidents.

**When NOT to apply.** Two genuine exceptions:

1. **The host's `/etc/docker/daemon.json` already enforces sane defaults.** Per-service `logging:` is then redundant. But verify — many teams *think* their hosts are configured and aren't; an explicit per-service block makes the constraint visible in the compose file itself.
2. **Truly ephemeral one-shot containers** (init jobs, migration runners with `restart: "no"` per COMPOSE-012) — they exit within seconds and produce trivial log volume. The default is fine.

Long-lived services (`restart: unless-stopped`, anything in COMPOSE-009
territory) should always declare `logging:` explicitly.

---

## COMPOSE-019 — Use `include:` for modular compose stacks

**What.** Compose v2.20+ supports a top-level `include:` directive that
pulls in one or more *separate* compose files as part of the current
project. Each included file is a complete compose document — its
services, networks, volumes, configs, and secrets all become part of
the parent project.

```yaml
# compose.yaml — the root project
include:
  - path: ./infra/database.yaml
  - path: ./infra/cache.yaml

services:
  api:
    build: .
    depends_on:
      postgres:
        condition: service_healthy
```

Relative paths in an included file resolve from **the included file's
location**, not the root project's. That's a deliberate design choice:
each sub-application is self-contained — its `build:` contexts,
`env_file:` paths, and `volumes:` host paths all stay relative to where
it lives.

Cite: [compose-file/include](https://docs.docker.com/reference/compose-file/include/).

**Why.** Before `include:`, two patterns existed for splitting a
compose project across files, both with real downsides:

1. **`-f file1.yaml -f file2.yaml` on the CLI.** File-level merge —
   services with the same name combine. Works, but every operator has
   to remember the file list, and relative paths in the override file
   resolve from the *first* file's directory (not the override's),
   which causes confusing path bugs.
2. **`extends:` per service (COMPOSE-010).** Service-level inheritance.
   Works for sharing one service's config, but doesn't help when you
   want to import a whole sub-stack (db + migrator + admin UI as a
   unit).

`include:` fixes both. The included file is its own coherent
sub-application; it can be developed and tested independently
(`docker compose -f infra/database.yaml up`), and dropped into a
larger project with one line. It's the right primitive for the
"shared infra block reused across several apps" pattern.

**Remote sources.** Compose ≥2.34 can also resolve a Compose
application published as an OCI artifact — `include: - oci://registry/org/app:tag`
in a file, or `docker compose -f oci://registry/org/app:tag up` on the CLI
(and Git sources the same way).

**Security note.** [CVE-2025-62725](https://github.com/docker/compose/security/advisories/GHSA-gv8h-7v7w-r22q)
(October 2025) was a path traversal in the resolution of **any** remote
OCI compose artifact — `include: oci://`, `-f oci://`, or anything else that
pulls one: attacker-controlled layer annotations let the artifact write
files outside Compose's cache directory. Local `path:` includes were never
affected. Fixed in Compose v2.40.2 — see COMPOSE-028 before using a remote
source.

**How.** Simple project structure:

```
.
├── compose.yaml              # root project — composes the pieces
├── infra/
│   ├── database.yaml         # postgres + migrator
│   └── cache.yaml            # redis
└── services/
    ├── api/
    │   ├── Dockerfile
    │   └── compose.yaml      # api service block — runnable standalone too
    └── worker/
        ├── Dockerfile
        └── compose.yaml
```

```yaml
# compose.yaml
include:
  - path: ./infra/database.yaml
  - path: ./infra/cache.yaml
  - path: ./services/api/compose.yaml
  - path: ./services/worker/compose.yaml
```

```yaml
# services/api/compose.yaml
services:
  api:
    build: .          # resolves to ./services/api/ (relative to *this* file)
    env_file:
      - .env          # resolves to ./services/api/.env
    depends_on:
      postgres:
        condition: service_healthy
```

For passing environment from the parent to the included file, use the
expanded include form:

```yaml
include:
  - path: ./services/api/compose.yaml
    project_directory: .                 # override the relative-path base
    env_file: ./.env                     # vars available to the included file
```

`include:` differs from `extends:` (COMPOSE-010) in scope:

| Feature | Scope | Use when |
|---|---|---|
| `include:` | File-level — pulls in a whole compose document | Composing sub-applications; sharing infra across projects |
| `extends:` | Service-level — merges one service's config from another file | Deduplicating boilerplate across services within one project |
| `-f file1 -f file2` | File-level merge by CLI argument | Environment-specific overrides (`compose.prod.yaml`); the dev overlay is the auto-loaded `compose.override.yml` (COMPOSE-005) |

**When NOT to apply.**

- Single-file compose projects — `include:` is overkill when the whole stack already fits in one `compose.yaml`.
- When you want environment-specific *overrides* of the same services (dev vs prod). Use `compose.override.yml` (COMPOSE-005) or `-f compose.prod.yaml`; `include:` is for composing distinct sub-applications, not overlaying variants of the same one.
- Compose versions older than v2.20 — the directive is unknown and the parser errors out. Pin a recent Compose in CI or fall back to multi-file `-f` invocations.

---

## COMPOSE-020 — Use the `gpus:` shorthand for GPU services

**What.** Compose ≥2.30 ships a top-level `gpus:` field on a service
that replaces the older `deploy.resources.reservations.devices` GPU
declaration. The new form is one line:

```yaml
services:
  trainer:
    image: nvidia/cuda:12.3.2-base-ubuntu22.04
    gpus: all                              # all available GPUs
    command: ["nvidia-smi"]
```

Or scoped:

```yaml
services:
  inference:
    image: myorg/inference:latest
    gpus:
      - driver: nvidia
        count: 1                          # one GPU
        capabilities: [gpu, compute]
```

**Why.** The old way — through `deploy.resources` — works, but it's
verbose, Swarm-flavored, and most operators don't remember the exact
schema. Compare:

```yaml
# old — pre-2.30
services:
  trainer:
    image: nvidia/cuda:12.3.2-base-ubuntu22.04
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

```yaml
# new — Compose ≥2.30
services:
  trainer:
    image: nvidia/cuda:12.3.2-base-ubuntu22.04
    gpus: all
```

The old form lives under `deploy.resources`, which behaves differently
between Swarm and standalone Compose — `deploy.resources.reservations`
is silently ignored outside Swarm for *most* fields but **was** honored
specifically for `devices.gpu`. That inconsistency was confusing.
`gpus:` is a top-level service field with spec-documented
standalone-Compose semantics, no Swarm caveats.

It's also what the docs now lead with — examples on
[docs.docker.com](https://docs.docker.com/compose/how-tos/gpu-support/)
use `gpus:` exclusively for Compose ≥2.30. The longhand still works
for backward compatibility.

**How.** Common patterns:

```yaml
# All visible GPUs (typical for single-host single-tenant workloads)
services:
  trainer:
    gpus: all

# Specific count
services:
  inference:
    gpus:
      - count: 2

# Specific device IDs (multi-tenant host where you partition GPUs)
services:
  worker-0:
    gpus:
      - device_ids: ["0"]
  worker-1:
    gpus:
      - device_ids: ["1"]

# Driver + capabilities (rare — only when you need non-default driver or capability set)
services:
  cuda-compute-only:
    gpus:
      - driver: nvidia
        count: 1
        capabilities: [compute, utility]    # skip the `graphics` capability
```

Cite: [Compose GPU support](https://docs.docker.com/compose/how-tos/gpu-support/),
[compose-file/gpus](https://docs.docker.com/reference/compose-file/services/#gpus).

The container still needs the NVIDIA Container Toolkit installed on
the host (`nvidia-container-runtime` / `nvidia-ctk`) — Compose only
*declares* the GPU need; the runtime does the actual mount. If
`docker compose up` reports "could not select device driver 'nvidia'",
the host toolkit isn't installed, not a compose issue.

**When NOT to apply.**

- Compose <2.30 — the `gpus:` field is unknown. Stay on the `deploy.resources.reservations.devices` longhand until you can bump Compose.
- Swarm mode deployments — `deploy.resources` is the Swarm-native interface; keep using it. `gpus:` is for standalone Compose.
- Non-NVIDIA GPUs (AMD ROCm, Intel) — the `driver:` field accepts other strings, but the ecosystem support is thinner. Verify your runtime supports the driver string before relying on the shorthand.

---

## COMPOSE-021 — Use the top-level `models:` block for AI model dependencies

**What.** Compose ≥2.38 ships a [Docker Model
Runner](https://docs.docker.com/ai/model-runner/)
integration (Model Runner runs on Docker Engine on Linux as well as
Docker Desktop): a top-level `models:` block declares language-model
dependencies the way `secrets:` and `configs:` declare other resources.
Services reference models, and Compose injects connection URLs as env
vars at start time.

```yaml
services:
  api:
    build: .
    models:
      - llm_small
      - llm_large
    # LLM_SMALL_URL / LLM_SMALL_MODEL and LLM_LARGE_URL / LLM_LARGE_MODEL are set in the container's env

models:
  llm_small:
    model: ai/llama3.2:1b
  llm_large:
    model: ai/llama3.3:70b
```

Cite: [compose-file/models](https://docs.docker.com/reference/compose-file/models/),
[Use AI models in Compose](https://docs.docker.com/ai/compose/models-and-compose/),
[Docker Model Runner](https://docs.docker.com/ai/model-runner/).

**Why.** Before `models:`, hooking a Compose app up to a local LLM
meant running an inference server (ollama, llama.cpp, vLLM) as a
separate service, exposing its port, and hand-wiring a connection URL
into the app. Three things go wrong:

1. **Boilerplate per app.** Every project re-implements the same "spin up ollama, point at it" pattern.
2. **Model lifecycle is wrong.** Models are large (gigabytes) and slow to download. Putting them inside an image bloats it; mounting them via volume requires out-of-band setup; pulling at startup adds minutes to `compose up`. None of those handle "share one model across many projects" well.
3. **No connection-URL convention.** Each project invents its own env var name. `OLLAMA_HOST`, `LLM_URL`, `OPENAI_API_BASE`, etc. — confusing across projects.

The `models:` block makes the model a first-class dependency: Compose
owns model lifecycle (downloads on demand, caches across projects), and
the connection details are injected via a predictable env var name
pattern derived from the model key — `<KEY>_URL` and `<KEY>_MODEL`
(`llm_small` → `LLM_SMALL_URL`, `LLM_SMALL_MODEL`), no prefix.

The Model Runner backend is OpenAI-compatible, so the app side can use
any OpenAI client by pointing it at the injected URL:

```python
from openai import OpenAI
client = OpenAI(base_url=os.environ["LLM_SMALL_URL"], api_key="not-needed")
```

**How.** Minimal "summarizer with two models" example:

```yaml
services:
  summarizer:
    build: .
    models:
      - small        # SMALL_URL, SMALL_MODEL
      - large        # LARGE_URL, LARGE_MODEL
    ports: ["8000:8000"]

models:
  small:
    model: ai/llama3.2:1b
    context_size: 4096
  large:
    model: ai/llama3.3:70b
    context_size: 8192
```

To rename the injected env var (e.g. for legacy apps that expect a
specific name):

```yaml
services:
  summarizer:
    models:
      llm:
        endpoint_var: OPENAI_API_BASE     # → OPENAI_API_BASE=http://...
        model_var:    OPENAI_MODEL_NAME   # → OPENAI_MODEL_NAME=ai/llama3.2:1b

models:
  llm:
    model: ai/llama3.2:1b
```

To use an externally-managed model (already pulled / managed via
`docker model pull`):

```yaml
models:
  llm:
    external: true
    name: ai/llama3.2:1b
```

The `ai/` namespace on Docker Hub hosts the community-curated model
collection; you can also reference any OCI artifact in the
[OCI Artifact Manifest format](https://github.com/opencontainers/image-spec/blob/main/manifest.md)
that the Model Runner understands.

**When NOT to apply.**

- Production deployments — Model Runner is a single-host feature. Production model serving belongs on a real inference platform (vLLM, TGI, managed model API). Use `models:` for local dev / dev containers; use a proper inference service in production.
- Compose <2.38, or hosts without Model Runner installed (on Linux it is a separate Docker Engine plugin). Model dependencies don't resolve without it.
- Models large enough that disk pressure becomes a real constraint — multiple devs each pulling 40GB of weights can saturate a build farm fast. For shared-runner CI, prefer pointing at a hosted model API.

---

## COMPOSE-027 — Use `post_start` / `pre_stop` lifecycle hooks for privileged setup/teardown

**What.** Compose ≥2.30 supports per-service `post_start` and `pre_stop`
lifecycle hooks — commands that run after the container starts and before
it's stopped, each able to set `privileged: true` independently of the
service's own privilege level.

**Why.** The usual ways to do post-boot registration (announce to a
service registry, warm a cache) or pre-stop work (flush a buffer, take a
backup) are to bake them into the entrypoint — coupling unrelated
concerns — or to grant the whole service elevated privileges it doesn't
otherwise need. Hooks keep the service's runtime posture minimal
(COMPOSE-023) while letting a *specific* setup step run privileged.

**How.**

```yaml
services:
  app:
    image: myapp:1.2.3
    post_start:
      - command: /usr/local/bin/register-with-mesh.sh
    pre_stop:
      - command: /usr/local/bin/drain-and-flush.sh
```

**When NOT to apply.** `pre_stop` does **not** run on a crash or `kill`
(only on graceful stop), so don't rely on it for correctness-critical
teardown — that belongs in a supervisor or an idempotent external job.
On Compose older than 2.30 the keys are ignored; gate on the version.

---

## COMPOSE-028 — Require Compose ≥2.40.2 (or v5) before using `include:` with OCI/registry sources

**What.** Pin a Compose version of at least 2.40.2 (every v5 release
postdates the fix) before using the `include:` directive (COMPOSE-019)
with OCI-artifact sources, or running a remote application with
`docker compose -f oci://...`.

**Why.** CVE-2025-62725 (CVSS 8.9): a path-traversal via the **layer
annotations** of *any* remote OCI compose artifact Compose resolves —
`include: oci://`, `-f oci://`, or an artifact that itself extends
another — let a malicious
remote compose model write files outside the project directory — e.g.
overwrite `~/.ssh/authorized_keys` — and it triggered even on a read-only
command like `docker compose ps` or `config`. Pulling a poisoned shared
compose module was enough; no `up` required. Fixed in Compose v2.40.2.

Cite: [GHSA-gv8h-7v7w-r22q](https://github.com/docker/compose/security/advisories/GHSA-gv8h-7v7w-r22q).

**How.**

```bash
docker compose version        # ensure >= v2.40.2 (or any v5.x)
```

Pin the Compose/CLI version in CI images and developer setup; treat
remote `include:` sources with the same supply-chain caution as base
images (SEC-010, SEC-021).

**When NOT to apply.** Stacks that only `include:` **local** files are
not exposed to this specific vector — but the fix is free and the version
floor is worth adopting regardless, since `ps`/`config` were enough to
trigger it.

---

## COMPOSE-029 — Set `init: true` on services whose image has no init process

**What.** When a long-lived service's image runs the app directly as
PID 1 — no `tini`/`dumb-init` `ENTRYPOINT` (DOCKER-006) — set
`init: true` on the service. Compose then runs Docker's init (the same
binary as `docker run --init`) as PID 1, which forwards signals to the
app and reaps zombie processes.

**Why.** A process running as PID 1 gets no default signal handlers: a
`SIGTERM` the app doesn't explicitly handle is ignored, so `docker compose
stop`/`down` waits out the 10-second grace period and then `SIGKILL`s it —
no graceful shutdown, dropped in-flight requests, unflushed buffers. PID 1
also inherits every orphaned child; an app that spawns subprocesses (shell
wrappers, headless browsers, `git`) without reaping them accumulates
zombies until the PID limit is hit. You often can't rebuild a third-party
image to add an init; `init: true` fixes it from the compose file.

**How.**

```yaml
services:
  worker:
    image: ghcr.io/vendor/worker:2.3.1@sha256:...   # runs its binary as PID 1
    init: true
```

Cite: [compose reference — init](https://docs.docker.com/reference/compose-file/services/#init).

**When NOT to apply.** Images that already ship an init as their
`ENTRYPOINT` (DOCKER-006 applied) — a second init adds nothing. It does
not replace DOCKER-006 for images you build: bake the init into the image
so it behaves the same under `docker run`, Kubernetes and Compose.

---
