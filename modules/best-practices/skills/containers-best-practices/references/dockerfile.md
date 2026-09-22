# Dockerfile rules

Detailed explanation for each `DOCKER-NNN` rule. Each entry follows the same
shape: **What / Why / How / When NOT to apply**.

Citations point at [the official Dockerfile reference](https://docs.docker.com/reference/dockerfile/)
and [Docker's build best-practices guide](https://docs.docker.com/build/building/best-practices/).
When training-data certainty is borderline, verify against those before claiming
a specific syntax or flag.

---

## DOCKER-001 — Use multi-stage builds for compiled or dependency-heavy apps

**What.** Split the build into stages: a `builder` stage with full toolchains
(compilers, dev headers, package manager caches), and a small `final` stage
that `COPY --from=builder` pulls only the artifacts it needs.

**Why.** Single-stage images carry every build dependency forever — gcc, npm
caches, `.git`, test fixtures, sometimes credentials. Real failure mode:
shipping a 1.4GB Node image to production because `node_modules` includes
devDependencies and the build toolchain. Multi-stage trims to the runtime
essentials and shrinks attack surface.

**How.**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev
COPY . .

FROM python:3.12-slim AS final
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH"
USER 10001
ENTRYPOINT ["python", "-m", "src.main"]
```

**When NOT to apply.** Pure interpreted single-file scripts with no
dependencies, throwaway debug images, or when you genuinely need the build
tools at runtime (uncommon — usually a sign something is wrong).

---

## DOCKER-002 — Pin base images by digest

**What.** Reference base images as `image@sha256:...`, not by tag alone.

**Why.** Tags are mutable. `python:3.12-slim` today is not the same blob as
`python:3.12-slim` next week. That breaks reproducibility, hides supply-chain
swaps, and can silently introduce CVEs (or fix them, which also matters for
auditability). Digest pinning makes the build bit-for-bit reproducible.

**How.**

```dockerfile
FROM python:3.12-slim@sha256:740d94a19218c8dd584b92f804b1158f85b0d241e5215ea26ed2dcade2b9d138 AS builder
```

Tooling like [Renovate](https://docs.renovatebot.com/docker/) or [Dependabot](https://docs.github.com/en/code-security/dependabot)
can keep digests up-to-date automatically. For repos without that tooling,
keep the tag as a comment for readability: `FROM python:3.12-slim@sha256:... # 3.12-slim, updated 2026-05-01`.

**When NOT to apply.** Quick local experiments, ephemeral CI images that
don't need reproducibility, base images you control yourself and tag
immutably. Even then, prefer digests in long-lived files.

---

## DOCKER-003 — Order layers cache-friendly: dependency manifests first, source last

**What.** Copy and install dependencies *before* copying application source.
Layers above the most-frequently-changing file invalidate on every build.

**Why.** Docker's layer cache invalidates a step when its inputs change.
`COPY . .` before `RUN pip install` means every source edit reinstalls every
dependency — turning a 3-second rebuild into a 90-second one.

**How.**

```dockerfile
# good — manifest copied first, deps installed, then source
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ ./src/
```

```dockerfile
# bad — any source change rebuilds deps
COPY . .
RUN uv sync --frozen --no-dev
```

For Node: `COPY package.json package-lock.json ./` then `RUN npm ci`, then
`COPY . .`. Same pattern for Go (`go.mod`/`go.sum`), Rust (`Cargo.toml`/`Cargo.lock`),
etc.

**When NOT to apply.** Almost never. The only case is languages where the
build genuinely needs all source present to resolve dependencies — and even
then a two-pass build often beats single-pass.

---

## DOCKER-004 — `COPY` only what's needed; rely on `.dockerignore`

**What.** Prefer explicit `COPY src/ ./src/` over `COPY . .`. Combined with a
strict `.dockerignore`, this keeps the build context small and predictable.

**Why.** `COPY . .` is a footgun: it picks up whatever is in the working
directory, including secrets that were accidentally placed there (`.env`,
private keys), large local caches (`__pycache__`, `node_modules`), and
artifacts from previous builds. It also inflates the build context Docker
sends to the daemon, slowing every build.

**How.**

- Be specific about what gets copied: `COPY src/ pyproject.toml ./`.
- Pair with a `.dockerignore` that excludes everything irrelevant (see SEC-001).
- When you do need `COPY . .` (e.g. Go monorepos), make the `.dockerignore` aggressive.

**When NOT to apply.** Simple repos where the build context is genuinely the
whole repo and `.dockerignore` is comprehensive. Even then, the explicit form
is more self-documenting.

---

## DOCKER-005 — Run as a non-root user in the final stage

**What.** The final stage must end with a `USER` directive that points at a
non-root account. Use a numeric UID (e.g. `USER 10001`) for compatibility
with Kubernetes `runAsNonRoot` policies.

**Why.** A container that runs as root and is then compromised gives the
attacker root inside the container — and on misconfigured hosts, that's a
small step from root on the host (especially with kernel exploits or mounted
sockets). Modern orchestration (Kubernetes, OpenShift, Nomad) increasingly
refuses to run root containers by default.

**How.**

```dockerfile
# create a real user (so /etc/passwd entry exists for libraries that need it)
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

USER 10001
WORKDIR /app
ENTRYPOINT ["/app/entrypoint"]
```

For distroless: use the `:nonroot` variant (`gcr.io/distroless/cc-debian12:nonroot`),
which ships with UID 65532 already configured.

Watch for files that need to be readable/writable by the non-root user —
`chown` them in the build stage before the `USER` switch.

**When NOT to apply.** When the workload genuinely needs root (binding to
ports <1024 without `CAP_NET_BIND_SERVICE`, kernel modules, system-level
debugging containers). In those cases, document *why* and consider whether
Linux capabilities (`--cap-add NET_BIND_SERVICE`) would suffice instead.

---

## DOCKER-006 — Use `tini`/`dumb-init` (or `--init`) for proper PID 1 / signal handling

**What.** Linux treats PID 1 specially: it does not get default signal
handlers, and it must reap zombie children. Most applications are not
written to be PID 1. Use a tiny init process (`tini`, `dumb-init`) or run
the container with `--init`.

**Why.** Without a real init, your app may not receive `SIGTERM` from
`docker stop`/Kubernetes — leading to forced `SIGKILL` after the grace
period, lost in-flight requests, corrupted state, and 30-second pod
shutdowns when 1-second would do. Forked child processes can also become
zombies that accumulate over time.

**How.**

```dockerfile
# Option A — bake tini into the image
RUN apt-get update && apt-get install -y --no-install-recommends tini && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "src.main"]
```

```bash
# Option B — pass --init at run-time. Docker uses tini under the hood
# (the `docker-init` binary on the host, backed by tini), but you can't
# pass tini-specific flags this way. If you need tini args, bake tini in (Option A).
docker run --init myimage
```

Cite: [docker run --init](https://docs.docker.com/reference/cli/docker/container/run/#init).

In Kubernetes, the right knob is a real init container or an init-aware
process inside your container — `shareProcessNamespace: true` is unrelated
to PID 1 reaping (it merely shares the PID namespace across containers in
a pod, useful for debugging sidecars).

A few application runtimes do the right thing without tini — distroless
images, supervisord-style entrypoints, and some language servers. **Don't
assume a runtime is init-aware just because it's "modern."** Most aren't.
Verify by sending `SIGTERM` and watching shutdown behavior. Node, in
particular, handles SIGTERM/SIGINT in newer versions but does **not** reap
zombie children — if your app forks subprocesses, you still need a real
init.

**When NOT to apply.** When your runtime genuinely provides proper init
behavior (verified, not assumed). Verify by sending `SIGTERM` and
watching the shutdown behavior — don't infer from a version number.

---

## DOCKER-007 — Add `HEALTHCHECK` for long-lived services

**What.** Declare a `HEALTHCHECK` instruction so the container can self-report
liveness/readiness. Orchestrators use this to decide when to restart, route
traffic, or move on with `depends_on: condition: service_healthy` (see
COMPOSE-001).

**Why.** Without a healthcheck, "container is running" means "the process
exists" — not "the process is serving requests." A web server can deadlock,
a DB connection pool can starve, and `docker ps` will still report `Up`.

**How.**

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1
```

Pick a check that exercises the real failure mode (DB connectivity, dependent
service reachable) — not just `pid 1 is alive`. Set `--start-period` to skip
the boot window where transient failures are expected.

In Kubernetes, prefer pod-level `livenessProbe`/`readinessProbe` and skip
the Dockerfile `HEALTHCHECK` (Kubernetes ignores it). For docker-compose and
plain `docker run`, the Dockerfile-level healthcheck is what's used.

**When NOT to apply.** Short-lived batch containers (CLI tools, cron jobs).
For jobs, exit-code semantics are what matters, not liveness.

---

## DOCKER-009 — Use `RUN --mount=type=cache` for package managers (BuildKit)

**What.** BuildKit provides cache mounts that persist across builds without
becoming part of the image. Mount one at the package manager's cache
directory to make repeat installs fast.

**Why.** Without a cache mount, every time a manifest changes, the package
manager re-downloads every package. With a cache mount, only the diff is
fetched — typical speedup is 5–20× for repos with many dependencies.

**How.**

```dockerfile
# syntax=docker/dockerfile:1

# uv (Python)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# pip (Python)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# npm
RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefer-offline --no-audit

# apt (use sharing=locked to avoid race; clean lists outside the mount)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl
```

Requires BuildKit (SEC-002) and the `# syntax=` directive at the top of the file.

**When NOT to apply.** When builds happen on a fresh CI runner with no cache
persistence — the cache mount won't help and the syntax overhead isn't worth
it. (Though many CI providers persist BuildKit caches with the right config.)

---

## DOCKER-010 — Don't bake secrets into layers; use `RUN --mount=type=secret`

**What.** Never `ARG` or `ENV` a secret. Use BuildKit's secret mount to
inject credentials at build time without persisting them in any layer.

**Why.** `ARG` and `ENV` values are visible in `docker history`, in image
layer metadata, and to anyone with pull access to the registry. Build
arguments also land in the build's provenance attestation (`mode=max`
records their values — BUILDX-008), so even an `ARG` that never reaches
a layer leaks through the attestation. Real failure mode: NPM tokens, AWS
keys, and private package registry creds showing up in public registries.

**How.** Expose the secret as an environment variable for one `RUN` only
(`env=` needs Dockerfile syntax ≥1.10):

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=npm_token,env=NPM_TOKEN \
    npm ci
```

```bash
docker buildx build \
  --secret id=npm_token,src=$HOME/.npmrc-token \
  -t myimage .
```

Cite: [Dockerfile reference — RUN --mount=type=secret](https://docs.docker.com/reference/dockerfile/#run---mounttypesecret),
[build secrets](https://docs.docker.com/build/building/secrets/).

For runtime secrets, use orchestrator-native mechanisms (Kubernetes Secrets,
Docker secrets, Vault sidecar) — not env vars baked into the image.

**When NOT to apply.** Genuinely public values (e.g. a public API base URL).
Default to "this is a secret" unless you're sure it isn't.

---

## DOCKER-011 — Minimize the final image: distroless / alpine / slim

**What.** Use the smallest base image that meets your runtime needs.
Roughly: distroless < alpine < `*-slim` < full distro.

**Why.** Smaller images = faster pulls, less attack surface, fewer CVEs to
triage. Distroless images contain no shell, package manager, or `coreutils`
— attackers can't `curl | sh` even if they get code execution.

**How.** Tradeoff cheat sheet (sizes are approximate; verify for your specific tag):

| Choice | Approx size | Pros | Cons | When to pick |
|---|---|---|---|---|
| `*-slim` (Debian) | 70–150 MB | Familiar tooling, glibc, full wheel compatibility | Larger than minimal alternatives | Default — works with the widest software set |
| Alpine | 5–15 MB | Very small | musl libc; some Python/Node native deps still ship glibc-only wheels | Pure Go/Rust; Node when tested with musl; Python only when you've verified your full dependency tree has musllinux wheels |
| Distroless (`static`/`base`/`cc`) | 2–30 MB | No shell, no package manager, smaller attack surface | No shell = harder to debug; need glibc-aware build stage | Production runtime for compiled binaries; Python via `gcr.io/distroless/python3` (~50 MB+, not as tiny) |
| Scratch | ~0 MB | Smallest possible | Bring your own everything (certs, timezone data, libc if needed) | Static Go/Rust binaries; when you really know what you need |

For **Python on Alpine specifically**: the old "always quintuples build
times" advice is now stale. [PEP 656](https://peps.python.org/pep-0656/)
defined the `musllinux` wheel platform tag, and many top-tier packages
(NumPy, pandas, SciPy, Pillow, cryptography, lxml, psycopg, orjson) ship
musllinux wheels today. For applications whose entire dep tree has
musllinux wheels available, Alpine is a perfectly fine Python base.

The honest 2026 guidance: check [PyPI's "Download files" section](https://pypi.org/)
for each top-N dependency — if all show `*-musllinux_*` wheels, Alpine
is fine; if any only ship `*-manylinux_*` wheels, that dependency will
build from source on Alpine (slow, requires a build toolchain in the
image). Long-tail and proprietary packages often still don't ship
musllinux, so `slim` remains the safer default for arbitrary
`pip install -r requirements.txt` workloads.

For Distroless Python: `gcr.io/distroless/python3` is significantly
larger than the `static`/`base`/`cc` variants because it bundles a
CPython runtime — don't expect "distroless = always smallest."

**When NOT to apply.** Debug images and dev containers (you *want* shell and
tools there). Workloads that need many system libraries — sometimes the
"full" image is genuinely the right call.

---

## DOCKER-012 — Set `WORKDIR` explicitly

**What.** Always declare `WORKDIR` before `COPY` or `RUN` operations that
expect a specific directory. Don't rely on the default (`/`).

**Why.** Running as `/` is brittle: relative paths resolve against root,
package managers may scatter files, and security policies often disallow
writing to `/`. `WORKDIR` also creates the directory if missing — `cd`
inside a `RUN` step would fail if the dir doesn't exist.

**How.**

```dockerfile
WORKDIR /app
COPY . .
RUN make build
```

**When NOT to apply.** Single-stage images that genuinely do nothing but run
`/usr/local/bin/foo` and have no working-directory expectations (rare).

---

## DOCKER-013 — Prefer `ENTRYPOINT` (exec form) + `CMD` over shell-form commands

**What.** Use the JSON array (exec) form: `ENTRYPOINT ["python", "-m", "app"]`.
Avoid the shell form: `ENTRYPOINT python -m app`.

**Why.** Shell form wraps your process in `/bin/sh -c "..."`, making the
shell PID 1 instead of your app. Signals (`SIGTERM`) go to the shell, not
your process, so graceful shutdown breaks. Exec form runs your binary
directly as PID 1.

**How.**

```dockerfile
# good — exec form, app is PID 1 (combine with DOCKER-006 for proper init)
ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--port", "8080"]
```

```dockerfile
# bad — sh -c wraps the process; signals don't reach python
ENTRYPOINT python -m src.main
```

When you need shell features (env var expansion, command chaining), use an
entrypoint script:

```dockerfile
COPY entrypoint.sh /usr/local/bin/entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["myapp"]
```

The script itself can use shell features, but the `ENTRYPOINT` directive
stays in exec form. **Critical footgun:** the script must end with
`exec "$@"` (or `exec <cmd>`), not a bare invocation. Without `exec`,
the script remains PID 1 and your real process becomes a child — signals
hit the script, not your app, and you've recreated exactly the problem
the exec form was meant to fix:

```bash
#!/usr/bin/env sh
set -e
# ... init work ...

# good — replaces shell with the command; signals reach the app
exec "$@"
```

```bash
#!/usr/bin/env sh
# bad — script stays PID 1, signals don't reach the app
"$@"
```

This is the single most common way exec-form entrypoints still get signal
handling wrong.

**When NOT to apply.** Almost never. The exec form is strictly better
unless you specifically need shell-feature expansion at startup, in which
case use an entrypoint script.

---

## DOCKER-014 — Use HereDoc syntax for multi-line `RUN` statements

**What.** Prefer BuildKit's heredoc form for multi-line commands instead of
backslash-continued `&&` chains.

**Why.** Heredocs are more readable, easier to diff, harder to break with
a stray trailing space after `\`, and copy/pasteable into a shell for
debugging. They're also forgiving about command boundaries — adding or
removing a line doesn't require fixing trailing `&&` and `\` on neighbors.

**How.**

```dockerfile
# syntax=docker/dockerfile:1
RUN <<EOF
set -eux
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates
rm -rf /var/lib/apt/lists/*
EOF
```

```dockerfile
# good — exec form with a specific shell + pipefail
RUN <<-"BASH" /bin/bash -eo pipefail
  curl -fsSL https://example.com/tool.tar.gz | tar -xz -C /opt
  /opt/tool/install.sh
BASH
```

Heredocs work with any `RUN` step that BuildKit handles. The `set -eux`
prefix (or `set -eo pipefail`) makes errors visible — without it, the
default `sh -c` keeps going after a failing step.

**When NOT to apply.** Single-command `RUN` lines (the heredoc adds noise).
Pre-BuildKit builders (the legacy builder doesn't parse this syntax) —
though everything modern uses BuildKit (SEC-002).

---

## DOCKER-015 — Use `set -o pipefail` for piped commands inside `RUN`

**What.** When a `RUN` step contains a pipe (`|`), prefix it with
`set -o pipefail` (or use bash explicitly) so the step fails if *any*
command in the pipeline fails — not just the last one.

**Why.** Docker runs `RUN` steps through `/bin/sh -c` by default, which
only checks the exit status of the *last* command in a pipeline. Real
failure mode: `RUN curl -fsSL https://example.com/installer.sh | sh` —
if `curl` fails (network down, URL moved, 404), `sh` still happily reads
an empty pipe and exits 0. Your build "succeeds" with nothing installed.

**How.**

```dockerfile
# good — pipefail catches curl failures
RUN set -o pipefail && curl -fsSL https://example.com/installer.sh | sh
```

For images whose default shell is `dash` (Debian/Ubuntu — `/bin/sh` is
dash, not bash, and dash doesn't support `pipefail`), use the exec form
to run bash explicitly:

```dockerfile
RUN ["/bin/bash", "-c", "set -o pipefail && curl -fsSL https://example.com/installer.sh | sh"]
```

Or change the default shell once for the whole Dockerfile:

```dockerfile
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]
# pipefail now applies
RUN curl -fsSL https://example.com/installer.sh | sh
```

Reference: [Docker — Using pipes in RUN](https://docs.docker.com/build/building/best-practices/#using-pipes).

**When NOT to apply.** `RUN` steps with no pipes — pipefail is irrelevant
there. Throwaway local images where silent failures are OK (rare; the
debugging cost almost always outweighs the noise of an extra flag).

---

## DOCKER-016 — Prefer `COPY --link` for content that doesn't depend on prior `RUN` mutations

**What.** `COPY --link` (and `ADD --link`) lets BuildKit attach the copy's
output as an independent overlay layer rather than as a child of the
previous layer. The result is more cache-stable across base-image
rebases and supports parallel layer fetching. Use it for any `COPY` /
`ADD` whose inputs don't depend on changes made by earlier `RUN` steps
in the same stage.

**Why.** `--link` is a **per-instruction** modifier, not a stage-wide
discipline. Its benefits apply to the specific layer it's set on:

- The linked layer can be re-mounted on a new base without rebuild.
- Multiple linked `COPY` steps can be fetched/extracted in parallel.
- When you bump the base image digest (DOCKER-002), all `--link` layers above the change stay cached; only the base itself needs to be re-pulled.

A later **non-linked** `COPY` invalidates cache for itself and the
instructions below it, but it does **not** retroactively un-link the
`--link` layers above. The "mix linked + non-linked breaks everything"
framing you may see in folklore isn't how BuildKit actually behaves —
the [Dockerfile reference](https://docs.docker.com/reference/dockerfile/#copy---link)
describes `--link` as per-instruction.

**How.**

```dockerfile
# good — all the COPYs are independent of any prior RUN mutation, so all use --link
FROM python:3.12-slim AS app
WORKDIR /app
COPY --link pyproject.toml uv.lock ./
COPY --link src/ ./src/
COPY --link scripts/ ./scripts/
```

```dockerfile
# also fine — the COPY after a chown depends on the RUN, so it can't use --link
FROM python:3.12-slim AS app
WORKDIR /app
RUN useradd --system --uid 10001 app
COPY --link pyproject.toml uv.lock ./
# depends on the user from RUN; --link wouldn't help
COPY --chown=10001:10001 src/ ./src/
```

The key rule: **don't use `--link` when the copy needs to see filesystem
state created by an earlier `RUN`** in the same stage (chmod, chown,
mkdir of a target dir, etc.) — linked layers don't see RUN-introduced
changes from below.

**When NOT to apply.**

- The `COPY` depends on a prior `RUN` (ownership, permissions, target directory created mid-stage).
- The stage has only one `COPY` step and no base to rebase against (`FROM scratch` with a single artifact) — the optimization has no effect.
- BuildKit isn't enabled (legacy builder ignores `--link`).

---

## DOCKER-017 — Multi-platform builds: scope BuildKit cache IDs by `TARGETARCH`

**What.** When building for multiple platforms (`--platform linux/amd64,linux/arm64`),
include `${TARGETARCH}` in every `--mount=type=cache` `id=` so each arch
has its own cache slice. Otherwise concurrent multi-arch builds corrupt
each other's caches.

**Why.** Cache mount IDs default to the `target=` path, which is arch-blind.
A single builder running both amd64 and arm64 stages simultaneously sees
both writing to the same cache mount — and the resulting state contains
native binaries from both architectures mixed together. Common failure
mode: arm64 `esbuild`, `sharp`, or compiled Python wheels end up in the
amd64 cache and segfault at install time on the next amd64 build.

**How.**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
# declare inside the stage — predefined platform ARGs are not inherited from the global scope
ARG TARGETARCH

# good — cache scoped per arch
RUN --mount=type=cache,id=uv-${TARGETARCH},target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project

RUN --mount=type=cache,id=apt-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl
```

`sharing=locked` (vs the default `sharing=shared`) ensures only one builder
writes at a time within a single arch — combine both for safety.

**When NOT to apply.** Single-platform builds — `TARGETARCH` is fine to
include defensively, but the bug it prevents won't occur. If you only
ever build linux/amd64 on a single runner, the unscoped form is harmless.

---

## DOCKER-018 — Disable `docker-clean` before mounting an APT cache

**What.** Debian/Ubuntu slim images ship
`/etc/apt/apt.conf.d/docker-clean`, which runs a `DPkg::Post-Invoke` hook
deleting `/var/cache/apt/archives/*.deb` after every `apt-get install`.
If you mount a BuildKit cache at `/var/cache/apt`, the post-install hook
wipes the cache on every build. Remove the hook before the first
cache-mounted apt step.

**Why.** This is a silent footgun: the build looks like it's using the
cache (BuildKit reports a hit, the mount is there), but the actual `.deb`
files are deleted milliseconds after they're written. Subsequent builds
re-download every package. Cache hit rate looks great in `docker history`,
package download time stays the same.

**How.**

```dockerfile
# syntax=docker/dockerfile:1

# Disable the post-install cleanup hook + enable keeping downloaded packages
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
 && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' \
      > /etc/apt/apt.conf.d/keep-cache

# Now the cache mount actually persists .deb files across builds
ARG TARGETARCH
RUN --mount=type=cache,id=apt-${TARGETARCH},target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=apt-lists-${TARGETARCH},target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev
```

Note: with this pattern, *omit* the usual `rm -rf /var/lib/apt/lists/*`
inside the `RUN` — the cache mount lives outside the layer, so those
files don't bloat the final image anyway, and removing them defeats the
cache between steps.

Use the `Binary::apt::` prefix (not bare `APT::Keep-Downloaded-Packages`)
— that's the canonical scope; the unprefixed form has historical bugs
(see Debian bug #812111).

**When NOT to apply.** When you're not using a cache mount on apt
(uncommon — DOCKER-009 says you should). When the base image isn't
Debian/Ubuntu (Alpine, distroless, RHEL families don't have the hook).

---

## DOCKER-019 — `apt-get update` and `apt-get install` must share a `RUN`

**What.** `apt-get update` (which refreshes the package index) and
`apt-get install` (which uses that index) must execute in the same
`RUN` instruction. Splitting them across two `RUN` lines is broken in a
specific and confusing way.

**Why.** Docker caches each `RUN` independently. If `apt-get update`
lives in its own `RUN`, the cached layer holds the package index from
whatever timestamp the layer was originally built — possibly months ago.
On a rebuild, BuildKit sees no change to that `RUN` line, reuses the
cached layer, and the *next* `RUN apt-get install` line happily installs
from an arbitrarily stale index. The bug manifests as:

- `apt-get install` fails with "Unable to locate package X" for newly-published packages.
- Security patches don't get picked up because the cached index doesn't know they exist.
- Builds work on one machine and fail on another, depending on whose layer cache is "fresh enough."

This is documented at length in Docker's [build best-practices guide](https://docs.docker.com/build/building/best-practices/#apt-get)
as the canonical "apt-get cache busting" problem.

**How.**

```dockerfile
# bad — independent RUNs, update layer caches separately from install
RUN apt-get update
RUN apt-get install -y curl
```

```dockerfile
# good — single RUN; the layer is reused or busted as a unit
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
```

The same pattern applies to `apk` (`apk update && apk add`), `dnf`
(`dnf makecache && dnf install`), and `microdnf` — though most are
better-behaved than apt because they don't cache the index file the
same way. Apt is the worst offender, but the "update + install in one
RUN" idiom is portable hygiene.

When using BuildKit cache mounts on `/var/cache/apt` and
`/var/lib/apt/lists` (DOCKER-009 + DOCKER-018), keep update and install
together inside the *same* `RUN` even though the cache lives outside
the layer — the layer-vs-cache split is orthogonal to the
update-vs-install split.

**When NOT to apply.** Never on Debian/Ubuntu. On distros where the
package manager refreshes the index implicitly per-invocation (Alpine
`apk add` without an explicit `apk update` does this since 3.3), the
rule is moot — but follows the pattern anyway for consistency.

---

## DOCKER-020 — `apt-get install` needs `--no-install-recommends`

**What.** Always pass `--no-install-recommends` to `apt-get install`
(and the matching `dnf install --setopt=install_weak_deps=False` on
RHEL-family). Without it, apt pulls in every package's "Recommends:"
list — which historically includes documentation, man pages, GUI
helpers, and surprisingly heavy adjacent packages.

**Why.** Two costs:

1. **Image bloat.** Common case: installing `git` without `--no-install-recommends` pulls in `perl`, `liberror-perl`, `git-man`, `less`, `patch`, plus dependencies — adding ~40MB to a slim image for things the container will never use. Multiplied across several `apt-get install` lines, this is hundreds of MB.
2. **Attack surface.** Every installed binary is a potential CVE target. Recommends frequently pulls in network tools, debugging utilities, and language runtimes (perl, python2) that have nothing to do with the package you actually wanted.

The default behavior here is a hangover from desktop Debian/Ubuntu,
where pulling in recommends is conventionally helpful. In a container,
it's almost always wrong.

**How.**

```dockerfile
# bad — pulls in recommends
RUN apt-get update && apt-get install -y curl git

# good
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
```

If a *specific* recommended package is actually needed, name it
explicitly alongside the main package — this keeps the intent
auditable:

```dockerfile
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      git \
      git-lfs \
      less \
 && rm -rf /var/lib/apt/lists/*
```

For RHEL families (UBI, Rocky, Alma, Fedora):

```dockerfile
RUN dnf install -y --setopt=install_weak_deps=False --setopt=tsflags=nodocs \
      curl git \
 && dnf clean all
```

(`tsflags=nodocs` skips documentation, the RHEL analogue of
recommends bloat.)

**When NOT to apply.** Dev container *base* images that are
intentionally batteries-included for human use — but even then, prefer
to name the convenience packages explicitly rather than relying on
recommends. Production / runtime images should always use the flag.

---

## DOCKER-021 — `pip install` without `--no-cache-dir` (when no cache mount)

**What.** `RUN pip install <packages>` should pass `--no-cache-dir`
unless the install is wrapped in a BuildKit cache mount. Without the
flag, pip writes its wheel cache under `~/.cache/pip/` (typically
`/root/.cache/pip/`), and that directory persists into the resulting
layer.

**Why.** The pip wheel cache can easily reach 100–500MB for a
moderately-sized project (every wheel pip downloads, plus
already-built source distributions). It serves no purpose at runtime
— pip won't be invoked again — and just inflates the layer. This is
the most common cause of "why is my Python image 2GB" complaints.

There are two correct fixes, depending on whether you want
cross-build caching:

1. **Disable the cache entirely** — `--no-cache-dir` — when you don't need cross-build cache reuse (single-shot prod images, layer is already cached by `COPY pyproject.toml` ordering).
2. **Use a BuildKit cache mount** — `RUN --mount=type=cache,target=/root/.cache/pip` — when you *do* want cross-build cache reuse. The cache lives outside the layer, so no bloat.

Both achieve "no pip cache in the final image." Pick one.

**How.**

```dockerfile
# bad — pip cache lands in layer, +200MB for nothing
RUN pip install -r requirements.txt
```

```dockerfile
# good — option 1: no cache at all
RUN pip install --no-cache-dir -r requirements.txt
```

```dockerfile
# good — option 2: BuildKit cache mount (cross-build cache reuse, layer stays clean)
# syntax=docker/dockerfile:1
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt
```

Same pattern applies to other Python tools:

- `pip wheel` — `--no-cache-dir` (or cache-mount `/root/.cache/pip`)
- `pipx install` — cache-mount `/root/.cache/pip` works; `--no-cache-dir` propagates through if exported
- `poetry install` — set `POETRY_CACHE_DIR=/tmp/poetry-cache` + clean, or cache-mount it
- `uv` — see UV-002/UV-003 (uses its own cache, BuildKit-aware)

**When NOT to apply.** `pip install` inside a *builder* stage in a
multi-stage build where the final stage uses `COPY --from=builder
/app/.venv`. The builder-stage cache doesn't ship — the final image is
clean either way. Even then, `--no-cache-dir` is harmless and worth
keeping for habit.

---

## DOCKER-022 — Replace `MAINTAINER` with `LABEL`

**What.** The `MAINTAINER` instruction was [deprecated in Docker 1.13](https://docs.docker.com/reference/dockerfile/#maintainer-deprecated)
(January 2017). Use OCI-standard labels instead:

```dockerfile
LABEL org.opencontainers.image.authors="Jane Smith <jane@example.com>"
```

**Why.** Two reasons:

1. **`MAINTAINER` adds a layer.** `LABEL` writes to image metadata without adding a layer; `MAINTAINER` historically created a layer (mostly harmless, but unnecessary).
2. **Tooling alignment.** OCI image-spec labels (`org.opencontainers.image.*`) are read by registries (GitHub Container Registry uses `org.opencontainers.image.source` to link image → repo), security scanners (Trivy reports the maintainer from the OCI label, not `MAINTAINER`), and SBOM tools. `MAINTAINER` is ignored by all of them.

The directive still works — Docker hasn't removed it — but it produces
a deprecation warning and provides no value over `LABEL`.

**How.** Replace and expand:

```dockerfile
# bad — deprecated, no tooling reads it
MAINTAINER Jane Smith <jane@example.com>
```

```dockerfile
# good — OCI-standard labels (see DOCKER-023 for the full set)
LABEL org.opencontainers.image.authors="Jane Smith <jane@example.com>"
LABEL org.opencontainers.image.source="https://github.com/myorg/myapp"
LABEL org.opencontainers.image.licenses="Apache-2.0"
```

For ownership in a team context, `org.opencontainers.image.vendor` is
the conventional choice (`org.opencontainers.image.authors` is for
*author* identity; vendor is for *publisher* organization).

**When NOT to apply.** Never. `MAINTAINER` has no remaining use case
worth defending.

---

## DOCKER-023 — Declare OCI image labels for traceability

**What.** Production-bound images should declare the standard
[OCI image labels](https://github.com/opencontainers/image-spec/blob/main/annotations.md)
that link the image artifact back to its source. At minimum:

| Label | Value |
|---|---|
| `org.opencontainers.image.source` | URL of the source repository (`https://github.com/myorg/myapp`) |
| `org.opencontainers.image.revision` | Git SHA the image was built from |
| `org.opencontainers.image.version` | Semver or release tag (`1.4.2`, `v2.0.0-rc1`) |
| `org.opencontainers.image.created` | RFC 3339 build timestamp |
| `org.opencontainers.image.licenses` | SPDX expression (`Apache-2.0`, `MIT AND BSD-3-Clause`) |
| `org.opencontainers.image.title` | Short human title |
| `org.opencontainers.image.description` | One-paragraph description |

**Why.** Without these labels, an image pulled from a registry is
opaque: you can't link it to a git commit, a build pipeline, a
license, or a release notes URL. Concrete consequences:

- **Incident response.** Production hits a CVE in a 6-month-old image. Without `org.opencontainers.image.revision`, you're spelunking through CI logs trying to figure out what commit produced that tag.
- **Registry features.** GitHub Container Registry uses `org.opencontainers.image.source` to *link* the package back to the repo in the UI. Without it, the package shows as "owned by GitHub" with no repo connection.
- **SBOMs and license compliance.** Tools like `syft` and `trivy` extract these labels into the SBOM. Auditors looking for "what's running where, under what license" rely on them.
- **Renovate / Dependabot context.** Bots can read these labels to identify which image is which.

**How.** Pass build metadata as `--build-arg`s and write them into
labels:

```dockerfile
ARG GIT_SHA
ARG VERSION
# commit time (the SOURCE_DATE_EPOCH value), not the wall clock
ARG BUILD_DATE

LABEL org.opencontainers.image.source="https://github.com/myorg/myapp"
LABEL org.opencontainers.image.revision="${GIT_SHA}"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.title="myapp"
LABEL org.opencontainers.image.description="The myapp service — HTTP API for X"
```

```bash
docker build \
  --build-arg GIT_SHA=$(git rev-parse HEAD) \
  --build-arg VERSION=$(git describe --tags --always) \
  --build-arg BUILD_DATE=$(date -u -d "@$(git log -1 --pretty=%ct)" +%Y-%m-%dT%H:%M:%SZ) \
  -t ghcr.io/myorg/myapp:$(git describe --tags --always) .
```

Take `created` from the commit timestamp — the same value as
`SOURCE_DATE_EPOCH` (DOCKER-030) — not the wall clock: a wall-clock
`created` changes on every rebuild of the same commit, so the image
config, and therefore its digest, is never reproducible.

In GitHub Actions, `docker/metadata-action` populates these
automatically from the workflow context — but it sets `created` from the
time the action runs, so override that one label with the commit time:

```yaml
- name: Commit time for the created label
  run: echo "COMMIT_TIME=$(git log -1 --format=%cI)" >> "$GITHUB_ENV"
- uses: docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302 # v6.2.0
  id: meta
  with:
    images: ghcr.io/myorg/myapp
    labels: |
      org.opencontainers.image.created=${{ env.COMMIT_TIME }}
- uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
  with:
    labels: ${{ steps.meta.outputs.labels }}
```

`docker/metadata-action` is the path of least resistance — it emits
all the common OCI labels from the workflow's git context without
hand-managed build args.

Cite: [reproducible builds — git commit timestamps](https://docs.docker.com/build/ci/github-actions/reproducible-builds/#git-commit-timestamps).

**When NOT to apply.** Throwaway local images, scratch tests, dev
container *base* images that no one consumes from a registry. Anything
pushed to a shared registry should carry the minimum set above.

---

## DOCKER-024 — Avoid `chmod 777` / `chmod -R 777`

**What.** `chmod 777` and `chmod -R 777` grant world-readable,
world-writable, world-executable permissions to files or directories.
Almost always wrong; almost always papering over a different bug.

**Why.** Three reasons it's a red flag:

1. **It usually masks a UID mismatch.** The Dockerfile creates a file as root, then later switches `USER 10001`, and the non-root user can't write to the path. The right fix is `chown 10001:10001` (or `--chown=10001:10001` on `COPY`), not `chmod 777`. The latter "works" but leaves every other process in the container able to write the path too.
2. **Security boundary inside the container.** Multi-process containers, sidecars, and capability-restricted services rely on file permissions as one of the few in-container isolation mechanisms. World-writable everywhere collapses that boundary.
3. **It's a tell for cargo-culted fixes.** When a Dockerfile contains `chmod -R 777 /app`, the previous engineer probably hit a permission error, googled, found a Stack Overflow answer suggesting `chmod 777`, and moved on without understanding the actual UID/GID setup. That same misunderstanding is usually buried elsewhere in the Dockerfile too.

**How.** What to flag:

```dockerfile
# all of these are red flags
RUN chmod 777 /app
RUN chmod -R 777 /var/lib/myapp
RUN chmod 0777 /run/myapp
```

What to do instead — match the user that will run the app:

```dockerfile
# Create the app user and use --chown on COPY
RUN useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /sbin/nologin app
COPY --chown=app:app src/ /app/src/

# Or chown after creation
RUN mkdir -p /var/lib/myapp \
 && chown -R app:app /var/lib/myapp

USER app
```

For genuinely shared mutable state between users (rare in
containers — usually a sign you should split the container), use group
permissions and `chmod g+rwX`, not `0777`:

```dockerfile
RUN groupadd --gid 10000 shared \
 && mkdir -p /shared \
 && chown :shared /shared \
 && chmod 2775 /shared        # setgid + group rwx
```

**When NOT to apply.** Genuinely public-readable / public-executable
*world-readable only* (`chmod 755` / `chmod 644`) is fine and the
common case. The rule targets `0777` specifically. A documented
exception with a comment explaining *why* (e.g. "tmpfs mount shared
between two unrelated UIDs because the upstream tool hardcodes
ownership") is acceptable but rare.

---

## DOCKER-025 — `EXPOSE` should match what `CMD` actually binds

**What.** The `EXPOSE` instruction declares which ports the image
expects to use at runtime. It's *documentation*, not enforcement —
Docker doesn't actually open ports based on `EXPOSE`. But it should
agree with what the running process actually binds, because everything
downstream reads it as truth:

- `docker run -P` (capital P) publishes every `EXPOSE`d port to random host ports.
- Compose `expose:` (without `ports:`) defaults to the Dockerfile `EXPOSE`s.
- Reverse proxies (Traefik with its docker provider) auto-discover ports via `EXPOSE`.
- `docker inspect` and registry UIs surface `EXPOSE` as the "what this image listens on."

When `EXPOSE 8080` but the app binds `:3000`, every one of those
downstream tools is silently lying.

**Why.** Common failure modes:

- App was rewritten to listen on `8000` but the Dockerfile still says `EXPOSE 8080`. `docker run -P` publishes `8080`, the app is unreachable, and the bug looks like networking when it's documentation drift.
- `EXPOSE 3000 3001 3002` because the engineer copied a template; the app only uses `3000`. Traefik registers all three, the load balancer gets confused.
- `EXPOSE` missing entirely. `docker run -P` does nothing useful; compose can't auto-wire; the image is harder to consume.

**How.** Match `EXPOSE` to what `CMD`/`ENTRYPOINT` binds. Concrete:

```dockerfile
# bad — EXPOSE doesn't match
EXPOSE 8080
CMD ["uvicorn", "app:api", "--host", "0.0.0.0", "--port", "3000"]
```

```dockerfile
# good
EXPOSE 3000
CMD ["uvicorn", "app:api", "--host", "0.0.0.0", "--port", "3000"]
```

If the port is configurable, parameterize:

```dockerfile
ENV PORT=3000
EXPOSE 3000
CMD ["sh", "-c", "uvicorn app:api --host 0.0.0.0 --port ${PORT}"]
```

(Tradeoff: shell-form `CMD` defeats DOCKER-013. The cleaner alternative
is to bake `PORT` into the entrypoint script rather than into `CMD`.)

For images that serve multiple ports (an HTTP API + a metrics
endpoint), `EXPOSE` both, and verify each appears in the actual
listening configuration:

```dockerfile
EXPOSE 3000 9090
CMD ["myapp", "--api-port=3000", "--metrics-port=9090"]
```

**When NOT to apply.** Init / job containers that don't listen on any
port — omit `EXPOSE` entirely rather than declaring something fake.
Dev container base images that don't run a long-lived service also
omit it.

---

## DOCKER-026 — `curl ... | sh` without checksum verification

**What.** Pattern: `RUN curl -fsSL https://example.com/install.sh | sh`
(or `wget | bash`, `curl | python`). Downloads a script from a remote
URL and pipes it directly to a shell. This is the supply-chain
equivalent of `eval`.

Adding `set -o pipefail` (DOCKER-015) makes the *failure mode* better
(a network error fails the build instead of being silently ignored),
but does nothing about the *substance* — you're still executing
whatever bytes happened to come back from the URL.

**Why.** The integrity guarantees of TLS only cover transport: bytes
arrive unmodified from whoever currently controls that hostname's
certificate. They do **not** cover:

1. **Hostname compromise.** If the upstream is compromised (domain takeover, account hijack on the install-script host), every build silently picks up the malicious payload starting at the next build. There's no version pin, no diff, no review surface.
2. **Silent script changes.** Upstream updates the script — fixes a bug, changes default behavior, adds telemetry, switches to a new package mirror. Your build's behavior changes overnight with no Dockerfile diff.
3. **No audit trail.** `docker history` shows `RUN curl ... | sh` but not what that script actually did. SBOMs are useless because the installer's installed *something* with no metadata.

Real-world examples of this going wrong: the [event-stream npm hack](https://github.com/dominictarr/event-stream/issues/116)
inserted malicious code via a transitive dependency — and any Dockerfile
that ran `npm install` against the registry picked it up. The script-pipe
pattern is the same risk, just one layer up.

**How.** What to flag:

```dockerfile
# all of these are red flags
RUN curl -fsSL https://example.com/install.sh | sh
RUN wget -qO- https://example.com/install.sh | bash
RUN curl -fsSL https://example.com/setup.py | python -
```

What to do instead — pin a specific release artifact, verify a
checksum, then execute:

```dockerfile
# good — fetch, verify, execute
RUN set -eux \
 && curl -fsSL -o /tmp/install.sh \
      https://github.com/example/tool/releases/download/v1.2.3/install.sh \
 && echo "abc123def456...  /tmp/install.sh" | sha256sum -c - \
 && bash /tmp/install.sh \
 && rm /tmp/install.sh
```

For a single remote file, `ADD --checksum` (Dockerfile syntax ≥1.6) does
the fetch-and-verify in one instruction and is what Docker's
[best practices](https://docs.docker.com/build/building/best-practices/#add-or-copy)
now recommend for remote artifacts — the build fails if the digest
doesn't match:

```dockerfile
# syntax=docker/dockerfile:1
ADD --checksum=sha256:<sha256-of-the-file> \
    https://github.com/example/tool/releases/download/v1.2.3/tool-linux-amd64.tar.gz /tmp/tool.tar.gz
```

A Git source takes the commit SHA as its checksum
(`ADD --checksum=<commit-sha> https://github.com/org/repo.git#v1.2.3 /src`),
and `ADD --unpack=true` (syntax ≥1.17) extracts a remote archive
explicitly. See SEC-017.

Even better — fetch the *binary* directly and skip the install script:

```dockerfile
# best — install script is just a download+chmod helper anyway
ARG TOOL_VERSION=1.2.3
ARG TOOL_SHA256=abc123def456...
RUN curl -fsSL -o /usr/local/bin/tool \
      "https://github.com/example/tool/releases/download/v${TOOL_VERSION}/tool-linux-amd64" \
 && echo "${TOOL_SHA256}  /usr/local/bin/tool" | sha256sum -c - \
 && chmod +x /usr/local/bin/tool
```

For tools published as OCI images, the cleanest pattern is
`COPY --from=`:

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc /uv /usr/local/bin/uv
```

That's auditable, pinned, and bypasses the install-script question
entirely. Where the publisher attests its images, verify the pin once
(`gh attestation verify --owner astral-sh oci://ghcr.io/astral-sh/uv:0.12.17`).
UV-001 shows the pattern in detail.

Cite: [Dockerfile reference — ADD --checksum](https://docs.docker.com/reference/dockerfile/#add---checksum).

**When NOT to apply.** Genuinely interactive *human* use (a dev
container `postCreateCommand` running an installer for an end-user
tool) is lower-stakes — but even there, prefer the pinned-checksum
path because dev containers are rebuilt frequently. The rule applies
hardest to production / shared images.

---

## DOCKER-027 — Pin `# syntax=docker/dockerfile:1` at the top of every Dockerfile

**What.** The very first line of every Dockerfile should be the syntax
directive:

```dockerfile
# syntax=docker/dockerfile:1
```

This pins the BuildKit *frontend* parser — independent of the Docker
engine version — to the current stable v1 release of the Dockerfile
language. Build checks (`docker build --check`, DOCKER-029) need
Dockerfile frontend ≥1.8, which `:1` already tracks.

**Why.** Without the directive, BuildKit falls back to whatever frontend
the engine ships with — which on older hosts is years behind. The
features that *silently* degrade or stop working:

- `RUN --mount=type=cache` / `--mount=type=secret` / `--mount=type=ssh` (DOCKER-009, DOCKER-010, SEC-006, SEC-020).
- `RUN <<EOF` heredoc syntax (DOCKER-014).
- `COPY --link` / `ADD --link` (DOCKER-016).
- `COPY --exclude=` / `ADD --exclude=` (DOCKER-028) — stable since 1.19; `COPY --parents` (DOCKER-031) — stable since 1.20.
- `ADD --checksum=` (≥1.6, SEC-017) and `ADD --unpack=` (≥1.17).
- `RUN --mount=type=secret,env=` (≥1.10, DOCKER-010).
- `# check=...` directives and `--check` lint pragmas (DOCKER-029) — require ≥1.8.

The failure mode is usually a confusing parse error ("unknown flag:
--mount") on the older host, *not* a clear "your frontend is too old"
message. The fix is one line at the top of the file — there is no good
reason to omit it.

Cross-link [SEC-002](#sec-002--use-buildkit). SEC-002 makes the case
for *using* BuildKit; DOCKER-027 is the per-file declaration that the
file targets a known frontend version.

**How.** First line, always:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:...
```

Don't pin a minor to "require" a feature: `:1` always resolves to the
newest stable 1.x, so `:1.8` is a *downgrade* that freezes you out of
every later flag (`--exclude`, `--parents`, `env=` secrets) and security
fix. Pin a full version (or digest) only for a hard reproducibility
requirement, and bump it deliberately.

Docker's [frontend docs](https://docs.docker.com/build/buildkit/dockerfile-frontend/)
say: "We recommend using `docker/dockerfile:1`, which always points to
the latest stable release of the version 1 syntax." That tracks both
minor and patch updates, so you get new features and security fixes
without manual bumps.

**When NOT to apply.** Never. Even one-line throwaway Dockerfiles cost
nothing to annotate, and the line is the difference between "works on
my laptop" and "works on every BuildKit ≥0.10 host." The directive is
ignored by the legacy (pre-BuildKit) builder, so there's no
compatibility downside.

---

## DOCKER-028 — Use `COPY --exclude` to filter unwanted files from multi-file copies

**What.** BuildKit's [`COPY --exclude=<pattern>`](https://docs.docker.com/reference/dockerfile/#copy---exclude)
(stable since Dockerfile syntax 1.19, which `docker/dockerfile:1`
includes — earlier it was `-labs` only) lets a single `COPY` instruction exclude
matching files. Repeat the flag to exclude multiple patterns. Replaces
awkward "copy then `rm`" or "split into many narrow COPYs" workarounds.

**Why.** Before `--exclude`, two ugly options existed for "copy this
directory but skip these few files":

1. **Multiple `COPY` instructions** naming each subpath you want
   included. Verbose, fragile when new files appear, and produces an
   extra layer per instruction (each one is a cache key).
2. **`COPY` followed by `RUN rm`** — copies the unwanted file *into a
   layer*, then deletes it in a later layer. The file is still
   recoverable from the prior layer (`docker save` / `docker history`),
   which makes this a security footgun for secrets and a bloat footgun
   for large junk files.

`.dockerignore` works for the implicit `COPY . .` case but not when you
want to mostly include a subtree with a few targeted exceptions.
`--exclude` is the surgical tool: included files land in the layer,
excluded files never touch it.

Cross-link [DOCKER-004](#docker-004--copy-only-whats-needed-rely-on-dockerignore).
DOCKER-004 says "be specific about `COPY`"; `--exclude` is how you stay
specific without exploding into a dozen narrow copies.

**How.** Replace patterns like:

```dockerfile
# bad — file lands in layer 1, gets deleted in layer 2 but still occupies space
COPY src/ /app/src/
RUN rm -rf /app/src/test_fixtures /app/src/scratch.py
```

```dockerfile
# bad — every new top-level file in src/ needs another COPY line
COPY src/main.py src/cli.py src/utils.py /app/src/
```

with:

```dockerfile
# syntax=docker/dockerfile:1
COPY --exclude=test_fixtures --exclude=scratch.py src/ /app/src/
```

Excludes glob: `*` matches within a single path segment; `**` matches
multiple segments. `--exclude=**/__pycache__` cleanly skips bytecode
caches everywhere under the source. Multiple `--exclude=` flags AND
together (file is excluded if it matches *any* pattern).

```dockerfile
# real-world example: ship the package, skip tests + caches + sample data
COPY --exclude=**/__pycache__ \
     --exclude=**/tests \
     --exclude=**/*.pyc \
     --exclude=examples \
     src/ /app/src/
```

`ADD --exclude=` works the same way for the rare cases where `ADD` is
appropriate (SEC-017 covers when it isn't).

**When NOT to apply.**

- Frontends older than 1.19 (a pinned `# syntax=docker/dockerfile:1.18` or earlier) — the flag is unknown and the build fails. Pin a current `# syntax=docker/dockerfile:1` (DOCKER-027) or fall back to `.dockerignore` + narrow copies.
- When the exclusion is *project-wide* (build-context level) — that's `.dockerignore`'s job. Use `--exclude` for instruction-local filtering, not global rules.
- When the set of excluded files is large and unstable — at some threshold, an explicit allow-list (`COPY src/main.py src/cli.py /app/`) is clearer than a long exclude list.

---

## DOCKER-029 — Run `docker build --check` as a Dockerfile lint step in CI

**What.** Build checks (Buildx ≥0.15, Dockerfile frontend ≥1.8) are a built-in linter that audits a
Dockerfile against a curated rule set (best-practices, deprecations,
security smells) without actually executing the build. Run it on every
PR:

```bash
docker buildx build --check .
# or, with the classic frontend
docker build --check .
```

`--check` exits non-zero when it finds a violation, so it gates CI on its
own. To make an ordinary *build* (no `--check`) fail on violations too,
set `# check=error=true` in the Dockerfile, or pass it as a build
argument — it is a build-arg, not an environment variable:

```bash
docker buildx build --build-arg BUILDKIT_DOCKERFILE_CHECK=error=true .
```

Cite: [Build checks](https://docs.docker.com/build/checks/),
[Build checks reference](https://docs.docker.com/reference/build-checks/).

**Why.** Several rules already in this skill are *automatically*
caught by `--check`:

- `JSONArgsRecommended` — flags shell-form `ENTRYPOINT`/`CMD` (DOCKER-013).
- `LegacyKeyValueFormat` — flags `LABEL key value` style (DOCKER-022 adjacent).
- `MaintainerDeprecated` — flags `MAINTAINER` (DOCKER-022).
- `SecretsUsedInArgOrEnv` — flags secret-shaped `ARG`/`ENV` names (SEC-014).
- `UndefinedVar` — catches typo'd `${VAR}` references.
- `WorkdirRelativePath` — catches `WORKDIR` without leading `/` (DOCKER-012-adjacent).
- `ConsistentInstructionCasing`, `NoEmptyContinuation`, `StageNameCasing` — style.
- `ReservedStageName`, `MultipleInstructionsDisallowed`, `DuplicateStageName` — correctness.
- `CopyIgnoredFile` — flags a `COPY` whose source is excluded by `.dockerignore`: exactly the "explicitly `COPY .env`" leak that SEC-012/SEC-015 guard against, now caught mechanically at build time.
- `ExposeInvalidFormat` / `ExposeProtoCasing` — malformed or wrong-cased `EXPOSE` (DOCKER-025-adjacent).
- `RedundantTargetPlatform`, `FromPlatformFlagConstDisallowed` — `--platform` smells in `FROM` that defeat multi-platform builds.
- `UndefinedArgInFrom` — a `${VAR}` in a `FROM` line referencing an `ARG` that was never declared.

`--check` runs in seconds (no build) and provides a uniform PR-time
signal. Treating Dockerfile lint as "run if you remember" misses the
issues until they bite at runtime; wiring it as a required check
catches them at review time alongside the rest of the linters.

The frontend evolves: new rules land in `docker/dockerfile` minor
releases, and `# syntax=docker/dockerfile:1` (DOCKER-027) already tracks
the latest. Pinning an older minor silently runs fewer checks.

**How.** Local dev — run before pushing:

```bash
docker buildx build --check .
```

GitHub Actions — fail the workflow on any finding (`--check` exits
non-zero on violations):

```yaml
- uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
- name: Dockerfile lint
  run: docker buildx build --check .
```

To fail regular builds as well, put the directive at the top of the
Dockerfile:

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true
```

`# check=skip=<RuleName>[,<RuleName>...]` disables checks for the **whole
file** — there is no per-instruction form — so document the reason next
to it:

```dockerfile
# syntax=docker/dockerfile:1
# check=skip=JSONArgsRecommended

FROM alpine
# intentional shell form; documented exception
ENTRYPOINT /entrypoint.sh
```

Experimental checks are off by default; enable them with
`# check=experimental=all` (or the same value in the build-arg). Combine
parameters with `;`: `# check=skip=JSONArgsRecommended;error=true`.

**When NOT to apply.**

- Repositories using the legacy (non-BuildKit) builder — `--check` is BuildKit-only. Migrate (SEC-002) before adopting.
- Vendored / generated Dockerfiles you don't own — flag findings as informational rather than blocking, since you can't fix upstream.
- Throwaway local-only Dockerfiles — the check is cheap, but the gating story applies to shared / CI builds.

---

## DOCKER-030 — Reproducible image timestamps via `SOURCE_DATE_EPOCH` + `--rewrite-timestamp`

**What.** Make image builds bit-for-bit reproducible by pinning every
file's mtime to a single epoch. Set `SOURCE_DATE_EPOCH` to the commit
timestamp (or another stable value) and pass
`--output type=image,...,rewrite-timestamp=true` to `docker buildx
build` (BuildKit ≥0.13). All files in the resulting image carry the
same epoch as their mtime, and the image's own `created` timestamp is
normalized — so two builds of the same source produce two images with
the **same content digest**.

```bash
SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct) \
  docker buildx build \
    --output type=image,name=ghcr.io/myorg/myapp:${TAG},push=true,rewrite-timestamp=true \
    --provenance=mode=max \
    .
```

Cite: [Reproducible builds with GitHub Actions](https://docs.docker.com/build/ci/github-actions/reproducible-builds/),
[buildx image exporter — rewrite-timestamp](https://docs.docker.com/reference/cli/docker/buildx/build/#output).

**Why.** Without timestamp normalization, every build embeds the *wall
clock at build time* into:

- file mtimes inside the image layers,
- the image's top-level `created` annotation,
- some package managers' install records (apt's dpkg status, pip's wheel install metadata).

That means rebuilding the same commit on Tuesday and on Friday produces
**different content digests**, even though the source, lockfiles, and
base images are identical. Concrete consequences:

1. **Provenance verification gets weaker.** SLSA / cosign attestations
   bind a signature to a digest. If the digest moves on every rebuild,
   "I have a signature for digest X" doesn't help when production is
   running digest Y from the same commit.
2. **Cache reuse breaks across builders.** Two CI runners building the
   same commit produce non-identical images, so layer-level dedup at
   the registry only partially works.
3. **You can't prove a rebuild is clean.** Supply-chain attestation
   guidance (SLSA L3+) wants "rebuild from source produces the same
   artifact." Without timestamp normalization, you can't demonstrate
   that — the rebuilt image differs from the original *only* in
   timestamps, but you have no clean way to assert "these are
   equivalent."

`rewrite-timestamp=true` is the BuildKit-side fix. Pairing it with
`SOURCE_DATE_EPOCH` (the [reproducible-builds.org standard](https://reproducible-builds.org/specs/source-date-epoch/))
means every layer's file mtimes match the commit's epoch — consistent
and source-derived.

Reproducibility closes the "but was *this* the binary?" loophole that
versioned tags and digests alone can't answer.

**How.** GitHub Actions — derive the epoch from the commit and pass it
to buildx:

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  with:
    fetch-depth: 0   # so git log can find the commit
- name: Set SOURCE_DATE_EPOCH
  run: echo "SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct)" >> "$GITHUB_ENV"

- uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
- uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
  with:
    context: .
    push: true
    tags: ghcr.io/myorg/myapp:${{ github.sha }}
    outputs: type=image,name=ghcr.io/myorg/myapp:${{ github.sha }},push=true,rewrite-timestamp=true
    provenance: mode=max
    sbom: true
```

Local / GitLab / any shell-based CI:

```bash
export SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct)
docker buildx build \
  --output type=image,name=ghcr.io/myorg/myapp:${CI_COMMIT_SHA},push=true,rewrite-timestamp=true \
  --provenance=mode=max \
  --sbom=true \
  .
```

To verify reproducibility — build twice, compare digests:

```bash
SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct) docker buildx build \
  --output type=image,name=test:a,push=false,rewrite-timestamp=true .
SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct) docker buildx build \
  --output type=image,name=test:b,push=false,rewrite-timestamp=true .
docker buildx imagetools inspect test:a --raw | sha256sum
docker buildx imagetools inspect test:b --raw | sha256sum
# should match
```

Caveats worth knowing:

- **Non-deterministic build steps.** If a `RUN` step calls `date`, embeds random UUIDs, or fetches "latest" from a moving URL, those still vary. `SOURCE_DATE_EPOCH` only fixes mtimes — your build itself has to be reproducible too. Most language ecosystems (`uv sync --locked`, `npm ci`, `cargo build --locked`, `go build`) are reproducible by default; trouble comes from custom scripts.
- **Some package managers ignore the epoch.** apt's `dpkg` records install timestamps from its own clock unless you patch the database after install. For most images this is acceptable noise; for strict L3 reproducibility, install all packages in a single layer and `touch -d @${SOURCE_DATE_EPOCH}` the dpkg status file at the end.

**When NOT to apply.**

- Dev / debug images where timestamps inside the image are diagnostically useful and reproducibility doesn't matter.
- Projects with no supply-chain story to defend — adding SBOM + provenance + reproducibility together pays off when consumers actually verify. For an internal tool with three users, it's overkill.
- Frontends older than BuildKit 0.13 — `rewrite-timestamp` is unknown and silently ignored. Bump BuildKit before relying on it.

## DOCKER-031 — Use `COPY --parents` to preserve source directory structure

**What.** `COPY --parents <src> <dest>` (stable since Dockerfile syntax
1.20, which `docker/dockerfile:1` includes — earlier `-labs` only) keeps the source path structure
relative to the build context instead of flattening it into the
destination.

**Why.** Without `--parents`, `COPY src/pkg/*.py /app/` flattens every
matched file into `/app/`, colliding `a/x.py` and `b/x.py` and losing the
package layout. The workarounds are a `COPY` per directory or post-copy
`mkdir`/`mv` gymnastics — verbose and brittle the moment the tree changes.

**How.**

```dockerfile
# syntax=docker/dockerfile:1
# preserves src/pkg/ under /app/
COPY --parents src/pkg/*.py /app/
```

Pairs with `--exclude` (DOCKER-028) to copy a structured subtree minus a
few files.

**When NOT to apply.** When you actually want a flat destination (copying
a handful of files into one dir) — plain `COPY` is simpler. And on
frontends older than 1.20, fall back to per-directory copies.

Cite: [Dockerfile reference — COPY --parents](https://docs.docker.com/reference/dockerfile/#copy---parents).

---

## DOCKER-032 — Cap heavy `RUN` steps with build-time resource limits

**What.** `docker buildx build --resource cpu=2,memory=4g` (BuildKit
≥0.31 + frontend ≥1.25), or the `resource` attribute in a bake target,
caps CPU and memory for build steps.

**Why.** On a shared builder, one runaway compile (a `cargo build -j`,
a `webpack` run) can starve every other concurrent build, turning CI into
a noisy-neighbor lottery. A per-step cap bounds the blast radius without
serializing the whole pipeline.

**How.**

```bash
docker buildx build --resource cpu=2,memory=4g -t myapp .
```

**When NOT to apply.** Dedicated single-build runners where the build
*should* use the whole machine — limits just slow it down. Most builds on
isolated runners don't need this; reach for it when a shared builder shows
contention.

---

## DOCKER-033 — Pin `RUN --network=none` on steps that must not touch the network

**What.** Add `--network=none` to a `RUN` step that should run with no
network access, so any accidental fetch fails loudly instead of silently
pulling from the internet.

**Why.** A build that *claims* to be reproducible (DOCKER-030) or to
install only from already-present, pinned artifacts can be quietly
undermined by a stray `pip install`, `curl`, or `go get` inside a step.
`--network=none` makes the "this step is offline" intent enforceable —
the step fails if it reaches for the network, surfacing the hidden
dependency instead of baking a non-reproducible, unpinned pull.

**How.**

```dockerfile
# deps already vendored/copied; compiling must not fetch anything
RUN --network=none python -m compileall -q /app
```

**When NOT to apply.** Steps that legitimately need the network (the
actual `apt-get`/`uv sync`/`npm ci`). Use it on the *post-fetch* steps
(compile, test, assemble), not the fetch itself.

---
