# Security & build rules

Detailed explanation for each `SEC-NNN` rule. Covers `.dockerignore`,
BuildKit, image scanning, multi-platform builds, secret handling, supply-chain
hygiene, and layer minimization.

Citations point at [BuildKit docs](https://docs.docker.com/build/buildkit/),
[buildx docs](https://github.com/docker/buildx), [Trivy](https://aquasecurity.github.io/trivy/),
and [Grype](https://github.com/anchore/grype). Verify version-specific syntax
before claiming defaults — BuildKit features evolve.

---

## SEC-001 — Always have a `.dockerignore`

**What.** A `.dockerignore` at the build context root excludes files from
the context Docker sends to the daemon. Without it, *everything* in the
working directory is shipped to the build — slow, leaky, and often
including things that should never be in an image.

**Why.** Three failure modes:

1. **Performance** — `node_modules/` and `.venv/` can be hundreds of MB. Without `.dockerignore`, they get shipped every build, then potentially re-copied into the image.
2. **Cache invalidation** — files that change frequently (logs, editor swap files) bust the build cache even if your `COPY` doesn't reference them, because the build context hash includes them.
3. **Secrets** — `.env`, `.aws/credentials`, `.git/config` (which often contains tokens), private keys. `COPY . .` will happily slurp these into a layer.

**How.** A solid starter `.dockerignore` for most repos:

```
# VCS
.git
.gitignore

# Python
**/__pycache__
*.py[cod]
*$py.class
**/.venv
**/venv
.env
.env.*
!.env.example
**/.pytest_cache
**/.mypy_cache
**/.ruff_cache
**/dist
**/build
**/*.egg-info

# Node
**/node_modules
npm-debug.log
yarn-error.log
**/.next
**/.nuxt

# Editors
.vscode
.idea
*.swp
.DS_Store

# Docker itself
Dockerfile*
.dockerignore
compose*.yml
docker-compose*.yml

# Build artifacts and caches
# (comments must start the line: `target  # Rust` would be read as a pattern)
# Rust
**/target
# Java
**/.gradle
# Go (if you have one)
**/bin
coverage
*.log

# Secrets (defense in depth — they shouldn't be here, but if they are, exclude)
**/*.pem
**/*.key
**/secrets/
```

Patterns match from the context root (Go `filepath.Match`). `*.pem` or
`node_modules` excludes only `./x.pem` and `./node_modules`, so
`src/leak.pem` and `web/node_modules` still ship. Prefix any pattern
that can appear below the root with `**/`
([build context — matching](https://docs.docker.com/build/concepts/context/#matching)).

Tune per project. Critically, **exclude `.env*` but include `.env.example`**
(the `!.env.example` line above).

**When NOT to apply.** Never — every project should have one.

---

## SEC-002 — Use BuildKit

**What.** Build with BuildKit, not the legacy builder: `docker build`
on Docker Engine ≥23.0 (BuildKit is the default there), or
`docker buildx build` (buildx always drives BuildKit).

**Why.** BuildKit is required for `RUN --mount=type=cache` (DOCKER-009),
`--mount=type=secret` (DOCKER-010 / SEC-006), `--mount=type=ssh`,
`HEREDOC` syntax, named contexts, multi-stage parallelism, and SBOM/provenance
attestation. The legacy builder supports none of these. BuildKit is
**the default** builder since Docker Engine 23.0, so the old
`DOCKER_BUILDKIT=1` toggle is unnecessary on any current engine. The
legacy builder is **deprecated**; new projects should not rely on it.

Cite: [BuildKit](https://docs.docker.com/build/buildkit/),
[legacy builder deprecation](https://docs.docker.com/engine/deprecated/#legacy-builder-for-linux-images).

**How.** First line of any Dockerfile that uses BuildKit features:

```dockerfile
# syntax=docker/dockerfile:1
```

The `# syntax=` directive pins the *frontend* parser version —
independent of your Docker engine version — so the feature set you're
targeting is stable. **Use `:1`** (not a pinned minor like `:1.7`).
Docker's own [frontend docs](https://docs.docker.com/build/buildkit/dockerfile-frontend/)
say: "We recommend using `docker/dockerfile:1`, which always points to
the latest stable release of the version 1 syntax, and receives both
'minor' and 'patch' updates." Pin a specific minor only when you have a
hard reproducibility requirement and are willing to manually bump for
security patches.

For CI: enable buildx in the runner:

```yaml
- uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
```

**When NOT to apply.** Two real cases:

1. **Windows containers.** BuildKit lacks Windows-container feature parity, so legacy is currently the only path. This is the main remaining exception.
2. **Air-gapped environments** without internet access to fetch the frontend image. (Workaround: pull `docker/dockerfile:1` once into your local registry.)

Otherwise, BuildKit is strictly better and the legacy builder is on
borrowed time.

---

## SEC-004 — Build multi-platform with `buildx` only when needed

**What.** `docker buildx build --platform linux/amd64,linux/arm64` produces
images that run on both x86 and ARM. Useful for cross-architecture
deployment, but it doubles build time.

**Why.** Multi-platform is *necessary* when:

- Running on Apple Silicon dev machines + x86 production (or vice versa).
- Targeting Raspberry Pi / ARM cloud (Graviton, Ampere).
- Distributing a public image used across architectures.

It's *not necessary* when:

- All your deployment targets are x86_64.
- You only build for local dev on one architecture.

On a single-node builder, the non-native platform's stages run under
QEMU emulation, which is much slower for CPU-bound steps. Native
multi-arch runners (or one runner per arch, combined with
`docker buildx imagetools create` — `docker manifest` is still an
experimental command) avoid the emulation tax but add CI complexity
(BUILDX-006).

**How.**

```bash
docker buildx create --use --name multi
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag ghcr.io/myorg/myapp:v1 \
  --push \
  .
```

For cheaper builds, use native runners per architecture:

```yaml
# build amd64 on ubuntu-latest, arm64 on ubuntu-24.04-arm or self-hosted
# then `docker buildx imagetools create` to combine into a manifest list
```

**When NOT to apply.** When all targets are one arch. Don't pay the build
cost for portability you don't need.

---

## SEC-005 — Never leak `.git`, lockfile-only artifacts, or `node_modules` into images

**What.** Three specific things that show up in images more often than they
should:

- **`.git`** — pulls your entire repo history into the image, including any rotated/leaked secrets in old commits, and any branch names that hint at internal projects.
- **`node_modules` (or similar)** — bloats the image and may include native binaries built against the wrong libc.
- **Lockfile-only artifacts** — `target/` (Rust), `.gradle/`, `.idea/`, IDE caches, coverage reports.

All three are addressed by SEC-001 (`.dockerignore`), but they're common
enough specific footguns to call out.

**Why.** `.git` exposure is the worst: an attacker who pulls your image
can browse your entire git history. If anyone ever committed a secret and
later "removed" it (without rewriting history), it's still there. This has
caused real production credential leaks.

**How.** Make sure `.dockerignore` includes:

```
.git
.gitignore
node_modules
target
.gradle
coverage
*.log
.idea
.vscode
```

And — separately — don't write `COPY . .` followed by `RUN something-that-reads-all-files`.
If you need git metadata at build time (commit SHA for a version tag), pass
it as a build arg:

```dockerfile
ARG GIT_SHA
LABEL org.opencontainers.image.revision=$GIT_SHA
```

```bash
docker build --build-arg GIT_SHA=$(git rev-parse HEAD) .
```

**When NOT to apply.** Never — these belong out of images.

---

## SEC-006 — Use BuildKit secret mounts for build-time credentials

**What.** When the build genuinely needs a credential (private package
registry token, SSH key for a private git dep), pass it via
`RUN --mount=type=secret` or `--mount=type=ssh`, not `ARG` or `ENV`.

**Why.** `ARG NPM_TOKEN=...` bakes the token into the image's history and
metadata, and build arguments are also recorded in the build's
provenance attestation (with `mode=max` their values too — BUILDX-008).
Anyone with pull access to the image can recover it. The secret
mount makes the credential available only inside that specific `RUN` step,
in a tmpfs that disappears after the step completes — nothing persists
into the resulting layer.

**How.** SSH for private git deps:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=ssh \
    git clone git@github.com:myorg/private-dep.git
```

```bash
ssh-add ~/.ssh/id_ed25519
docker buildx build --ssh default .
```

Token for a private package registry:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm ci
```

```bash
docker buildx build --secret id=npmrc,src=$HOME/.npmrc .
```

A tool that reads the credential from an environment variable gets it
with `env=` (Dockerfile ≥1.10) — scoped to that one `RUN`, never written
to a layer, and no `$(cat /run/secrets/...)` shell plumbing:

```dockerfile
RUN --mount=type=secret,id=gh_token,env=GH_TOKEN \
    gh release download v1.2.3 --repo myorg/tool
```

Cite: [build secrets](https://docs.docker.com/build/building/secrets/),
[build variables — build args in provenance](https://docs.docker.com/build/building/variables/).

For runtime secrets (DB passwords, API keys), use orchestrator-native
secret mechanisms (Kubernetes Secrets, Docker secrets, Vault sidecar) — not
build-time secrets and not env vars baked into the image.

**When NOT to apply.** Genuinely public build inputs (a public package
mirror URL). Default to "this is a secret" unless you're sure it isn't.

---

## SEC-008 — Minimize `RUN` layers without sacrificing readability

**What.** Combine related steps into a single `RUN`, but don't chain
unrelated work just to save a layer.

**Why.** Each `RUN` produces a new layer. Layers have overhead (metadata,
mount/unmount, potential cache misses), and old artifacts in a layer
persist even if later `RUN` steps delete them. The classic example:

```dockerfile
# bad — temporary apt lists persist in layer 1, deleted in layer 2 but still occupy space
RUN apt-get update && apt-get install -y curl
RUN rm -rf /var/lib/apt/lists/*
```

```dockerfile
# good — install and clean in one layer
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*
```

But don't take this to the extreme:

```dockerfile
# also bad — chains unrelated work, breaks cache reuse
RUN apt-get update && apt-get install -y curl \
 && curl -L https://example.com/installer.sh | sh \
 && pip install foo bar baz \
 && git clone https://github.com/me/repo \
 && make build
```

A single change to any of those busts the whole layer's cache. Split by
logical concern.

**How.**

- Combine: install + cleanup of the same package manager.
- Combine: download + verify + extract + cleanup of a single tool.
- Separate: distinct package managers, distinct logical phases, anything you want to cache independently.

```dockerfile
# system packages — combined install + cleanup
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# language deps — separate, cached against pyproject.toml/uv.lock
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# source — last, busts cache on any code change
COPY src/ ./src/
```

**When NOT to apply.** Tiny one-line `RUN`s where combining would hurt
readability without saving anything meaningful. The goal is *layer hygiene*,
not minimum layer count.

---

## SEC-009 — Use the compose `secrets:` block, not environment variables

**What.** For services that need credentials at runtime, declare them as
top-level `secrets:` and reference them from the service's `secrets:`
list. Compose mounts each one as a read-only file at `/run/secrets/<name>`.
Applications read the value from the file path, not from an env var.

**Why.** Environment variables leak through three independent channels,
all of which are easy to forget:

1. **`docker inspect <container>`** — anyone with Docker socket access sees every env var.
2. **`/proc/<pid>/environ`** — readable by any process in the same UID, and by `root` regardless. A compromised co-tenant or a debug-exec into the container exposes the env.
3. **Logs and errors** — many frameworks dump env on crash; many CI logs print the env at startup. Anything ever printed to a log lives forever.

File-mounted secrets bypass all three: they don't appear in `docker
inspect`, they're not in `/proc/<pid>/environ`, and they don't get
trivially logged. They are **not** access-controlled inside the
container, though: a `file:`-sourced secret is a bind mount of the host
file, mounted with the default mode `0444` — readable by every user in
the container — and Compose **silently ignores** `uid`, `gid` and `mode`
for `file:` sources (they are only implemented for `environment:`
sources). Treat the secret as readable by any process in the container,
and keep the host file itself `0600`/`0400`.

**How.**

```yaml
# compose.yml
services:
  api:
    build: .
    secrets:
      - postgres_password
      - jwt_secret
      - openai_api_key
    # Pydantic-settings, dynaconf, etc. can read directly from /run/secrets/*
    environment:
      SECRETS_DIR: /run/secrets   # tell the app where to look (non-secret pointer)

secrets:
  postgres_password:
    environment: POSTGRES_PASSWORD   # sources value from compose env / .env
  jwt_secret:
    environment: JWT_SECRET
  openai_api_key:
    file: ./secrets/openai_api_key   # or read from a host file
```

Application side, with [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/#secrets):

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    postgres_password: str
    jwt_secret: str
    openai_api_key: str

    model_config = SettingsConfigDict(secrets_dir="/run/secrets")
```

Then override the source-priority order so file-secrets always win, even
if an env var of the same name leaks in:

```python
@classmethod
def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
    return init_settings, file_secret_settings, env_settings, dotenv_settings   # files beat env, env beats .env
```

Keep `env_settings` ahead of `dotenv_settings`: the default order is
init, then "Environment variables", then "Variables loaded from a dotenv
(`.env`) file", then secrets
([Field value priority](https://docs.pydantic.dev/latest/concepts/pydantic_settings/#field-value-priority)).
Swapping those two lets a stale `.env` silently override the real
environment.

The `secrets:` block also accepts:

- `environment: VAR` — pull from compose's env at parse time (least secure of the three; OK for dev). The only source where the long-syntax `uid` / `gid` / `mode` take effect.
- `file: ./path` — read from a host file; bind-mounted, `0444`, `uid`/`gid`/`mode` ignored.
- `external: true` — reference a secret managed outside compose. Swarm only: plain `docker compose up` without Swarm rejects it ("unsupported external secret"). Use it with `docker stack deploy`.

Cite: [compose reference — services secrets](https://docs.docker.com/reference/compose-file/services/#secrets).

**When NOT to apply.** Genuinely non-secret config (log level, feature
flags, base URLs) — env vars are fine for those. The cost of the
indirection is small enough that "default to files for anything
sensitive" is the right policy.

---

## SEC-010 — Don't substitute ARGs in `@sha256:` digests; use literal version+digest pairs

**What.** Image references with a digest pin — `image:TAG@sha256:HEX` —
should be **fully literal**. Don't write `python:${VERSION}-slim@sha256:${DIGEST}`
or templatize the digest line in Jinja/copier. Pin the literal pair and
bump both together (Renovate, Dependabot, or by hand) when you want to
update.

**Why.** Two well-documented failure modes — both real, both silent in
the wrong way:

1. **Template drift.** In a Jinja/copier template, `python:{{ version }}-slim@sha256:abc...` re-renders the `version` but leaves the digest fixed. After a `version` bump (say 3.12 → 3.13), the digest still points at the *3.12* manifest. The digest wins (it's content-addressed) so the build keeps pulling 3.12 — but is now *named* 3.13. Your "Python 3.13" CI is silently still 3.12. The bug doesn't show up until someone notices the version mismatch, which can take months.
2. **Skipped lockstep updates.** If the version and digest live on separate lines or in separate variables, it's easy to bump one without the other (manually, or with a `regexManager` configured for only one of them). Renovate / Dependabot can keep version + digest in lockstep — but **only when written as a literal pair on a single line** that the tool's matcher can capture as a unit.

There is also a third, weaker concern: **ARG expansion in `FROM`** has
historically had parser edge cases (see [moby/buildkit#579](https://github.com/moby/buildkit/issues/579)
and adjacent issues around quoted/multi-stage `FROM` references). The
exact behavior of "ARG inside `@sha256:`" varies across builder
versions and is not well-documented either way. Even if your current
builder handles it correctly, "don't do clever things in `FROM`" is a
defensible heuristic — but the *primary* arguments for the rule are
template drift and tooling lockstep, both of which apply regardless of
builder behavior.

**How.** Always write the full literal:

```dockerfile
FROM python:3.12-slim@sha256:740d94a19218c8dd584b92f804b1158f85b0d241e5215ea26ed2dcade2b9d138 AS base
```

Same rule for `COPY --from` references to non-final stages:

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc /uv /uvx /bin/
```

For Renovate to keep these updated, configure a `regexManager` or use the
built-in `dockerfile` manager — both will bump version + digest as a pair.
A short comment makes the pair obvious to humans too:

```dockerfile
# Renovate: keep version + digest in lockstep
FROM python:3.12-slim@sha256:740d94a19218c8dd584b92f804b1158f85b0d241e5215ea26ed2dcade2b9d138 AS base
```

**Template recipe (Jinja/copier).** Keep the reference literal in the
template source so the template repo's own Renovate/Dependabot run bumps
it:

```dockerfile
# Dockerfile.jinja — no Jinja inside the image reference
FROM python:3.13-slim@sha256:<digest> AS base
```

If the version genuinely is a template question, make each choice a
**complete literal** `image:tag@sha256:...` string, and have a Renovate
[`customManagers`](https://docs.renovatebot.com/modules/manager/regex/)
regex (capturing `currentValue` and `currentDigest`) keep every choice
current:

```yaml
# copier.yml
python_image:
  type: str
  choices:
    "3.13": "python:3.13-slim@sha256:<digest-3.13>"
    "3.12": "python:3.12-slim@sha256:<digest-3.12>"
```

```dockerfile
FROM {{ python_image }} AS base
```

Never template the tag and the digest as separate variables
(`python:{{ ver }}-slim@sha256:{{ digest }}`) — nothing keeps them in
lockstep.

**When NOT to apply.** Throwaway local builds where you genuinely want
"newest matching tag" and don't care about reproducibility — drop the
digest entirely and rely on the tag alone. Don't mix the two.

---

## SEC-011 — Add `.venv` (and other platform-specific build dirs) to `.dockerignore`

**What.** Beyond the obvious `.git` / `node_modules` exclusions (SEC-001
/ SEC-005), make sure your `.dockerignore` excludes platform-specific
build artifacts the host may have created: Python's `.venv/`, Rust's
`target/`, Gradle's `.gradle/`, frontend `dist/`, plus tool caches like
`.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`.

**Why.** Two separate failure modes:

1. **Platform mismatch.** A `.venv/` built on macOS arm64 contains
   mach-o binaries that segfault inside a Linux container. Same for
   `node_modules/` with native addons (`sharp`, `esbuild`,
   `better-sqlite3`). The uv guide is [explicit](https://docs.astral.sh/uv/guides/integration/docker/#using-uv-in-docker):
   "It is best practice to add `.venv` to a `.dockerignore` file...
   the project virtual environment is dependent on your local platform
   and should be created from scratch in the image."
2. **Bloat and cache invalidation.** Even when the host artifacts are
   compatible, copying them into the build context inflates the context
   tarball (often by hundreds of MB) and busts the cache on every host
   build, because the artifacts change with every local run.

**How.** Extend the `.dockerignore` baseline from SEC-001:

```
# Python — platform-specific
.venv
venv
__pycache__
*.py[cod]
*$py.class
.pytest_cache
.mypy_cache
.ruff_cache
.tox
.nox

# Node — platform-specific
node_modules
.next
.nuxt
.parcel-cache

# Rust
target

# Java / Kotlin
.gradle
build

# Frontend build outputs
dist
out
.svelte-kit

# Tool caches
.cache
.turbo
```

If your repo has multiple language ecosystems, include all of their
build dirs — `COPY . .` doesn't care which subtree it's pulling from.

**When NOT to apply.** Never. These paths should not be in container
images regardless of stack.

---

## SEC-012 — Don't `COPY` `.env` files into images

**What.** Reject any `COPY .env`, `COPY *.env`, `COPY .env.*`, or wildcard
copy whose target resolves to a dotenv file. Even when `.dockerignore`
excludes `.env*`, an *explicit* `COPY` instruction in the Dockerfile
bypasses the ignore list — `.dockerignore` only filters the *implicit*
build-context send for `COPY .` / `COPY src/`, not for named-file copies.

**Why.** `.env` files almost universally contain real secrets:
`DATABASE_URL` with embedded password, `*_API_KEY`, `*_TOKEN`,
`AWS_SECRET_ACCESS_KEY`. Once `COPY .env /app/` runs, the file lives in
that layer **forever** — even if a later `RUN rm /app/.env` deletes it,
the file is recoverable from the prior layer via `docker save` /
`docker history`. Anyone who can `docker pull` the image can extract the
secret.

It's also a redundant layer of risk on top of SEC-001: most teams expect
`.dockerignore` to be the last line of defense, then a Dockerfile line
explicitly names the very file the ignore list excluded. The fix is to
never reference `.env` from a Dockerfile at all — provide secrets at
runtime via the compose `secrets:` block (SEC-009) or the orchestrator's
secret store.

**How.** What to flag:

```dockerfile
# all of these are problems
COPY .env /app/
COPY .env.production /app/.env
COPY *.env /app/
COPY .env.* /app/
# only a problem if .dockerignore doesn't exclude .env* (see SEC-001, SEC-015)
COPY . .
```

What to do instead — read secrets at runtime, not build time:

```dockerfile
# Dockerfile: no .env reference at all
COPY src/ /app/src/
COPY pyproject.toml uv.lock /app/
# secrets come in via /run/secrets/ at runtime (SEC-009)
```

```yaml
# compose.yml: supply the values at runtime via secrets: block
services:
  api:
    build: .
    secrets:
      - database_url
secrets:
  database_url:
    file: ./.env.database_url   # gitignored, never copied into image
```

If a build-time credential is genuinely required (private package
registry token), use a BuildKit secret mount (SEC-006), not `COPY`.

**When NOT to apply.** Copying a `.env.example` *template* that contains
only placeholder values (`DATABASE_URL=postgres://user:pass@host/db`) is
fine — but rename it to make the intent obvious (`env.example`,
`.env.template`) and double-check it contains no real values before
allowing the copy.

---

## SEC-013 — Add `.git/` to `.dockerignore` (and never `COPY .git`)

**What.** `.git/` must be excluded by `.dockerignore`, and no Dockerfile
instruction should explicitly `COPY .git` into a stage that ends up in
the final image. This is a *specific instance* of SEC-001 / SEC-005, but
flag it separately because the failure mode is uniquely severe.

**Why.** The `.git/` directory contains the **entire repository history**.
Three concrete failure modes:

1. **Rotated secrets are recoverable.** A secret committed once, then "removed" in a later commit (without `git filter-repo` / BFG history rewrite), still lives in the packfiles. Anyone with `docker pull` access can clone the embedded repo and recover it: `docker run --rm -v $(pwd)/out:/out image cp -r /app/.git /out && git -C out log -p`.
2. **Branch names + commit messages leak project intent.** Internal codenames, customer names in commit messages, references to private repos, security incident commits ("fix CVE-2024-X before disclosure") — all of it ships in the image.
3. **`.git/config` often contains tokens.** If anyone on the team has ever cloned with `https://x-access-token:$GITHUB_TOKEN@github.com/...` and that local clone became the build context, the token is now in the layer.

**How.** First line of `.dockerignore`:

```
.git
.gitignore
.gitattributes
.github
```

If the build genuinely needs the commit SHA for a version label, pass it
as a build arg, not via `.git`:

```dockerfile
ARG GIT_SHA
LABEL org.opencontainers.image.revision=$GIT_SHA
```

```bash
docker build --build-arg GIT_SHA=$(git rev-parse HEAD) .
```

If you need richer git metadata (tags, branch, dirty state) at build
time, compute it on the host into a file and `COPY` that single file —
not the whole `.git/` tree:

```bash
git describe --tags --dirty --always > build-info.txt
docker build .
```

```dockerfile
COPY build-info.txt /app/build-info.txt
```

**When NOT to apply.** Never. If a tool genuinely requires a `.git`
directory at build time (some `setuptools_scm` configurations,
`git-describe`-based version detection), use a multi-stage build: do the
git-aware work in a builder stage, then `COPY --from=builder` only the
computed artifacts into the final stage. The `.git/` directory must not
end up in the shipped image.

---

## SEC-014 — Don't put secrets in `ARG` or `ENV` names matching `*SECRET*` / `*TOKEN*` / `*PASSWORD*` / `*KEY*` / `*CREDENTIAL*`

**What.** Scan Dockerfiles for `ARG` and `ENV` instructions whose names
match common secret-indicating patterns:
`*SECRET*`, `*TOKEN*`, `*PASSWORD*`, `*PASS*` (when not `BYPASS`/`COMPASS`),
`*KEY*` (when not `KEYRING`/`KEYBOARD`/public-key suffixes), `*CREDENTIAL*`,
`*PRIVATE*`, `*API_KEY*`, AWS-style `AWS_SECRET_*`, `AWS_SESSION_TOKEN`.

If any of these appear, the credential is being injected the wrong way.
Both `ARG` and `ENV` bake the value into image metadata visible via
`docker inspect` and `docker history`, and build arguments are also
recorded in the provenance attestation (values included under
`mode=max`). The build check `SecretsUsedInArgOrEnv` (DOCKER-029) flags
the same names mechanically.

**Why.** This is the dual to SEC-006 (use secret mounts for build-time
credentials) and SEC-009 (use file-mounted secrets for runtime). The
difference here: **it's not about the value, it's about the name**. Even
if the value is empty / overridden later, the *presence* of a
secret-shaped ARG/ENV signals the wrong pattern was used somewhere — and
in practice the value is usually populated:

- `ARG NPM_TOKEN` + `docker build --build-arg NPM_TOKEN=$TOKEN` → token visible in `docker history` of every layer below the `ARG` line, forever.
- `ENV DATABASE_PASSWORD=hunter2` → value visible in `docker inspect <container>`, `/proc/<pid>/environ`, and any framework that dumps env on crash (SEC-009 walks through this).
- `ARG AWS_SECRET_ACCESS_KEY` → the worst case; cloud credentials with broad blast radius, written into layer metadata.

Pattern-matching on the *name* catches the bug at review time without
needing to know the value.

**How.** What to flag:

```dockerfile
# all of these are problems regardless of value
ARG NPM_TOKEN
ARG GITHUB_TOKEN
ARG DATABASE_PASSWORD=hunter2
ENV API_KEY=sk-abc123
ENV AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
ENV JWT_SECRET
# path is OK but the name pattern reads as secret-shaped — verify
ARG PRIVATE_KEY_PATH
```

Build-time secret → use a BuildKit secret mount (SEC-006):

```dockerfile
# good — env= needs Dockerfile syntax >= 1.10
RUN --mount=type=secret,id=npm_token,env=NPM_TOKEN \
    npm ci
```

```bash
docker buildx build --secret id=npm_token,env=NPM_TOKEN .
```

Runtime secret → use the compose `secrets:` block (SEC-009):

```yaml
services:
  api:
    secrets:
      - jwt_secret
secrets:
  jwt_secret:
    file: ./secrets/jwt_secret
```

**When NOT to apply.** Two genuine exceptions worth recognizing:

1. **Public keys / non-secret keys.** `ENV SIGNING_PUBLIC_KEY=...` or `ARG SSH_KNOWN_HOSTS_KEY` is fine — the name matches the pattern but the value is intentionally public.
2. **Pointers, not values.** `ENV SECRETS_DIR=/run/secrets` or `ENV API_KEY_FILE=/run/secrets/api_key` names a *path* and contains no secret material. Confirm the value before flagging.

In both cases, the name pattern is a heuristic that points at "look
closely here," not an automatic verdict. Inspect, then decide.

---

## SEC-015 — `.dockerignore` must be *comprehensive*, not just present

**What.** SEC-001 checks that a `.dockerignore` exists. This rule checks
that it actually excludes the dangerous categories — anyone can satisfy
SEC-001 with a one-line file that ignores `*.tmp`. The minimum-coverage
baseline:

| Category | Required patterns |
|---|---|
| **VCS** | `.git`, `.gitignore`, `.github` |
| **Secrets** | `.env`, `.env.*`, `!.env.example`, `**/*.pem`, `**/*.key`, `**/secrets/`, `**/.aws`, `**/.ssh`, `**/.kube`, `**/.gnupg` |
| **Platform-specific build dirs** | `**/node_modules`, `**/.venv`, `**/venv`, `**/__pycache__`, `**/target`, `**/.gradle`, `**/dist`, `**/build`, `**/.next`, `**/.nuxt` |
| **Tool caches** | `**/.pytest_cache`, `**/.mypy_cache`, `**/.ruff_cache`, `**/.turbo`, `**/.cache` |
| **Editors & OS** | `.vscode`, `.idea`, `.DS_Store`, `*.swp` |
| **Docker meta** | `Dockerfile*`, `.dockerignore`, `compose*.yml`, `docker-compose*.yml` |

**Why.** Empirically, `.dockerignore` files drift: someone adds it once
during scaffolding with three patterns, the repo grows new ecosystems
(adds a Python venv, adopts pnpm, picks up cargo), and the ignore list
never gets updated. Five months later `COPY . .` ships a 400MB
`node_modules` and a developer's `.env.local` because nothing flagged
the gap.

Checking for *existence* misses the most common real failure mode
(coverage gaps). Checking against a baseline catches it.

**How.** Run a diff between the project's `.dockerignore` and the
baseline above; flag any baseline category with zero matching patterns.
The most-missed category in practice is **secrets** — `.env*` and
private-key globs. The second most-missed is **per-ecosystem build
dirs** when the repo is polyglot (Python service that also has a
frontend, but only Python paths got ignored).

An **allowlist** file (`*` first, then `!src`, `!pyproject.toml`, ...)
covers every category by construction, so a per-category pattern check
must count a leading `*` as full coverage. Its gap sits *inside* the
re-included paths. The last matching line wins, so `!src` re-admits
`src/node_modules` and `src/.env` unless you exclude them again *after*
the `!` lines (`**/node_modules`, `**/.env`, `**/*.pem`, ...). Audit an
allowlist for re-excludes below its last `!` line, not for the baseline
categories.

A concrete starter that covers the baseline:

```
# VCS
.git
.gitignore
.gitattributes
.github

# Secrets — exclude all dotenv, allow only the template
.env
.env.*
!.env.example
**/*.pem
**/*.key
**/*.p12
**/secrets/
**/.aws
**/.ssh
**/.kube
**/.gnupg

# Python
**/__pycache__
**/.venv
**/venv
*.py[cod]
**/.pytest_cache
**/.mypy_cache
**/.ruff_cache
**/.tox
**/dist
**/*.egg-info

# Node / frontend
**/node_modules
**/.next
**/.nuxt
**/.svelte-kit
**/.parcel-cache
npm-debug.log*
yarn-error.log*

# Rust / Java / Go
**/target
**/.gradle
**/build
**/bin

# Tool caches
**/.cache
**/.turbo
coverage
*.log

# Editors / OS
.vscode
.idea
*.swp
.DS_Store

# Docker meta — don't recursively copy these into images
Dockerfile*
.dockerignore
compose*.yml
docker-compose*.yml
```

**When NOT to apply.** Unusual repos with documented reasons for
including paths the baseline excludes — e.g. a "secrets" directory that
genuinely contains *public* certificates, intentionally shipped in the
image. Document the deviation in a comment in `.dockerignore` itself.

---

## SEC-016 — Broad `COPY . .` without a matching `.dockerignore`

**What.** Reject `COPY . .` / `COPY . /app` / `ADD . .` and similar
whole-context copies when the build context has no `.dockerignore` — or
has one that fails the SEC-015 comprehensiveness check.

**Why.** Whole-context copies are the single highest-blast-radius
instruction in Dockerfiles. With no `.dockerignore` (or a sparse one),
they slurp:

- `.git/` and its history (SEC-013)
- `.env*` files with secrets (SEC-012)
- `.venv/` / `node_modules/` with platform-mismatched binaries (SEC-011)
- IDE state, OS metadata, logs, build artifacts (SEC-005)

The instruction itself isn't wrong — it's idiomatic and convenient — but
it's only safe when `.dockerignore` is actually doing its job. The two
rules form a pair: `COPY . .` *assumes* `.dockerignore` is comprehensive
(SEC-015). When that assumption silently breaks, every secret in the
working directory ships.

**How.** When you see `COPY . .` (or equivalent), check the same
build-context root for `.dockerignore`. If it's missing, fail SEC-001.
If it's present but incomplete, fail SEC-015. If it's comprehensive,
`COPY . .` is fine.

Lower-risk alternative when the project doesn't yet have a
comprehensive `.dockerignore` — copy specific subtrees instead:

```dockerfile
# narrow copies are safer because they don't depend on .dockerignore for safety
COPY pyproject.toml uv.lock /app/
COPY src/ /app/src/
COPY tests/ /app/tests/
```

This is verbose but explicit — every line names what enters the image.
The cost is maintenance (you remember to add new top-level dirs), the
benefit is that a missing `.dockerignore` can no longer leak secrets.

**When NOT to apply.** If `.dockerignore` is comprehensive (passes
SEC-015) and the project genuinely uses many top-level paths, `COPY . .`
is the right call. Don't force per-path copies just to feel safer — the
real safety boundary is `.dockerignore`, not the COPY syntax.

---

## SEC-017 — Prefer `COPY` over `ADD`; flag un-checksummed `ADD <url>` and local tar auto-extract

**What.** Use `COPY` for local files. Flag exactly two `ADD` patterns:
`ADD <url>` **without** `--checksum=`, and `ADD` of a local tar archive
that relies on implicit auto-extraction. `ADD --checksum=... <url>` is
the recommended way to fetch a remote artifact, not a violation.

`ADD` has two side effects `COPY` doesn't:

1. **Auto-extract local tar archives.** `ADD foo.tar.gz /app/` extracts the tarball — surprising, and almost never what the reader of the Dockerfile expects.
2. **Fetch remote URLs.** `ADD https://example.com/file.tar.gz /tmp/` downloads the URL during build — without `--checksum=` nothing verifies what came back.

**Why.** Both behaviors cause real bugs:

- **Tar auto-extraction is invisible.** Someone reading the Dockerfile sees `ADD foo.tar.gz /app/` and assumes a single file lands at `/app/foo.tar.gz`. Instead the tarball's contents explode into `/app/`, potentially overwriting files. The behavior depends on the file extension (`.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz` are all auto-extracted; `.zip` is not).
- **Remote `ADD` without `--checksum` skips verification.** `ADD https://example.com/installer.sh /tmp/` produces no checksum check, no signature validation, and gives the network endpoint silent write access into your image at build time. If `example.com` is ever compromised or the URL ever serves a different file, the build silently picks up the change.

**How.** Replace the patterns:

```dockerfile
# bad — auto-extracts, surprising
ADD release.tar.gz /opt/

# good — explicit extract with visible options
COPY release.tar.gz /tmp/
RUN tar -xzf /tmp/release.tar.gz -C /opt/ \
 && rm /tmp/release.tar.gz
```

```dockerfile
# bad — no checksum, silent supply chain
ADD https://example.com/tool-v1.2.tar.gz /tmp/tool.tar.gz

# good — the build fails if the download doesn't match (Dockerfile >= 1.6)
ADD --checksum=sha256:<sha256-of-the-file> \
    https://example.com/tool-v1.2.tar.gz /tmp/tool.tar.gz

# good — extract a remote archive explicitly (Dockerfile >= 1.17)
ADD --checksum=sha256:<sha256-of-the-file> --unpack=true \
    https://example.com/tool-v1.2.tar.gz /opt/tool/
```

A Git source takes the commit SHA as its checksum:
`ADD --checksum=<full-commit-sha> https://github.com/org/repo.git#v1.2.3 /src`.

Cite: [best practices — ADD or COPY](https://docs.docker.com/build/building/best-practices/#add-or-copy),
[Dockerfile reference — ADD](https://docs.docker.com/reference/dockerfile/#add).

**When NOT to apply.**

- `ADD --checksum=... <url>` — this is the recommended form, not a finding.
- `ADD --keep-git-dir=true <git-url>` for git-context builds where you want the `.git` directory preserved.
- An explicit `ADD --unpack=true` on a local archive — the extraction is visible, which is the whole point of the rule.

---

## SEC-019 — `.env` files must be in `.gitignore`, not just `.dockerignore`

**What.** SEC-001 / SEC-015 cover excluding `.env*` from the *Docker
build context*. This rule checks the *git working tree*: any `.env`,
`.env.local`, `.env.production`, etc. present in the repo root must be
listed in `.gitignore`, and must not already be tracked by git.

Specifically, flag:

1. `.env` exists in repo and **isn't** in `.gitignore`.
2. `.env` is in `.gitignore` but is **already tracked** (was committed before the ignore was added — `git rm --cached` is required to actually untrack it).
3. `.env*` patterns are in `.gitignore` but `.env.example` (or `.env.template`) is *also* ignored, so the template can't be committed.

**Why.** `.dockerignore` only protects the image. If `.env` is committed
to git, the secret is already in the repository history — every clone
of the repo (CI, contributors, fork) has the credential, and rotating
the secret without rewriting git history doesn't undo the exposure.
This is the most common secret-leak vector in practice and has nothing
to do with containers, but the `containers` plugin notices the symptom
(`.env` files near a Dockerfile) and can flag it.

The "tracked file in `.gitignore`" case is uniquely deceptive: the
file *looks* ignored (`git status` doesn't list it), but `git ls-files
.env` shows it's tracked — every commit still picks up changes.

**How.** Checks to run:

```bash
# 1. .env exists but not in .gitignore?
if [ -f .env ]; then
  git check-ignore .env >/dev/null 2>&1 || echo "FAIL: .env not gitignored"
fi

# 2. .env in .gitignore but already tracked?
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "FAIL: .env is tracked by git; run 'git rm --cached .env'"
fi

# 3. .env.example accidentally ignored?
if [ -f .env.example ] && git check-ignore .env.example >/dev/null 2>&1; then
  echo "FAIL: .env.example is gitignored — won't be committed as a template"
fi
```

A correct `.gitignore` shape:

```
# Real secrets — gitignored
.env
.env.local
.env.*.local
.env.development
.env.production

# Template — explicitly committed (not ignored)
!.env.example
```

If `.env` is already tracked, remediation is two steps — and rotating
the secrets it contained is mandatory because the value is in git
history:

```bash
git rm --cached .env       # untrack without deleting the local copy
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Stop tracking .env"
# Then: rotate every secret that was ever in the file. The values are still
# in git history and remain valid until rotated.
```

**When NOT to apply.** Single-developer prototypes with no real
credentials and no plans to share the repo — the rule still applies in
principle but the consequences are small. Don't disable the check; just
weigh the urgency.

---

## SEC-020 — Use `--mount=type=ssh` for SSH-agent forwarding during builds

**What.** When a build needs to clone a private git repository or
otherwise present an SSH identity (typical for vendored private deps),
use BuildKit's SSH-agent forwarding mount — `RUN --mount=type=ssh` —
combined with `docker buildx build --ssh default` at the CLI. The
build connects to the host's `ssh-agent` through a forwarded socket;
no key material ever touches the build context, a layer, or the
resulting image.

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=ssh \
    --mount=type=cache,target=/root/.cache/go-build \
    git clone git@github.com:myorg/private-dep.git /src/private-dep
```

```bash
ssh-add ~/.ssh/id_ed25519
docker buildx build --ssh default -t myimage .
```

**Why.** This rule promotes a paragraph buried in SEC-006 to first-class
status because the failure modes around SSH-in-builds are uniquely
dangerous and uniquely common:

1. **`COPY id_rsa` antipattern.** The naive "I'll copy my SSH key into the build context" approach bakes the key into a layer forever. `RUN rm` in a later layer doesn't help (layers are immutable; `docker save` recovers the file). The key is now exfiltratable by anyone with pull access — and SSH keys are usually long-lived and broadly authorized, so the blast radius is huge.

2. **`ARG SSH_PRIVATE_KEY`.** Same outcome, different path: `ARG` and `ENV` values are visible in `docker history` and `docker inspect`. Even if the value is immediately consumed, it's etched into image metadata.

3. **`.ssh` bind mount in dev containers leaking into builds.** Teams sometimes bind-mount `~/.ssh` into a dev container (DEVC-006 warns against this), then run `docker build` *inside* that dev container — the key is now in two places it shouldn't be.

`--mount=type=ssh` solves all three. The mount appears at
`/run/buildkit/ssh_agent.0` (the default; configurable via `target=`)
*only inside the specific `RUN` step* that requests it, and it's a
forwarded socket — not the key itself. The key never leaves the host
agent. The build step uses it transparently because `SSH_AUTH_SOCK`
is set to the mount path.

Cite: [Dockerfile reference — RUN --mount=type=ssh](https://docs.docker.com/reference/dockerfile/#run---mounttypessh),
[buildx --ssh](https://docs.docker.com/reference/cli/docker/buildx/build/#ssh).

**How.** The canonical pattern:

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.22 AS builder
WORKDIR /src

# Tell git to trust github.com's host key (otherwise the clone prompts and hangs)
RUN mkdir -p -m 0700 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts

RUN --mount=type=ssh \
    --mount=type=cache,target=/go/pkg/mod \
    git clone git@github.com:myorg/private-lib.git /src/private-lib && \
    cd /src/private-lib && go build ./...
```

```bash
# Make sure ssh-agent has the key
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

# Build with default forwarding (uses $SSH_AUTH_SOCK)
docker buildx build --ssh default -t myimage .
```

For Go modules that depend on private repos:

```dockerfile
# syntax=docker/dockerfile:1
ENV GOPRIVATE=github.com/myorg

# Rewrite https URLs to ssh so go-get uses the forwarded agent
RUN git config --global url."git@github.com:".insteadOf "https://github.com/"

RUN --mount=type=ssh \
    --mount=type=cache,target=/go/pkg/mod \
    go mod download
```

For npm private registries that need an SSH key (rare; tokens via
`--mount=type=secret` are more common — SEC-006):

```bash
docker buildx build \
  --ssh github=$HOME/.ssh/id_ed25519 \    # named identity instead of default
  -t myimage .
```

```dockerfile
RUN --mount=type=ssh,id=github \
    git clone git@github.com:myorg/private-npm-pkg.git
```

**Remote Git sources without a `RUN`.** `ADD` fetches a private repo over
SSH directly, using the same forwarded agent:

```dockerfile
# syntax=docker/dockerfile:1
ADD git@github.com:myorg/private-lib.git#v1.4.0 /src/private-lib
```

```bash
docker buildx build --ssh default .
```

For HTTPS Git sources, pass a token as the `GIT_AUTH_TOKEN` build secret,
scoped to one host with the `.<host>` suffix so it is never sent anywhere
else:

```bash
docker buildx build --secret id=GIT_AUTH_TOKEN.github.com,env=GITHUB_TOKEN .
```

Cite: [Dockerfile reference — ADD](https://docs.docker.com/reference/dockerfile/#add),
[build secrets — Git authentication](https://docs.docker.com/build/building/secrets/#git-authentication-for-remote-contexts).

**GitHub Actions caveat.** GHA has its own SSH-agent action
([webfactory/ssh-agent](https://github.com/webfactory/ssh-agent)) that
loads a deploy key into the runner's agent, after which `--ssh default`
works as on a developer laptop. Don't try to put the key in a GitHub
secret and `COPY` it into the build — that's the antipattern this rule
addresses.

**When NOT to apply.**

- The build doesn't need any private SSH-authenticated access. Public dependencies → no SSH mount needed.
- Build-time **token** auth (private package registry, deploy token) — use `--mount=type=secret` (SEC-006) instead. Tokens aren't SSH identities.
- Air-gapped / offline builds where no agent forwarding is possible. Vendor the private dependency into the build context instead, accepting the maintenance cost.

---

## SEC-021 — Pin third-party scanner/tool images by digest and CI Actions by commit SHA

**What.** Pin every third-party security scanner or build tool you pull
(Trivy, Grype, Docker Scout, syft/cosign images) by `@sha256:` digest,
and pin every GitHub Action by a full commit SHA — not a floating
`@v0` / `:latest` tag.

**Why.** In the March 2026 Trivy supply-chain compromise
([CVE-2026-33634 / GHSA-69fq-xp46-6x23](https://github.com/advisories/GHSA-69fq-xp46-6x23),
critical), attackers force-pushed 76 of 77 `aquasecurity/trivy-action`
tags and every `setup-trivy` tag to a credential stealer, and published
malicious `trivy` 0.69.4 binaries/images plus `aquasec/trivy:0.69.5`/`0.69.6`
images — anyone tracking a moving tag ran it. Fixed: `trivy-action`
≥0.35.0, `setup-trivy` ≥0.2.6; the last clean `trivy` before the
incident was 0.69.3. A mutable tag means an upstream compromise
runs *your* CI with *your* registry and cloud credentials in scope.
Pinning a digest/SHA makes the artifact immutable and the supply chain
auditable.

**How.**

```yaml
# pin the action by commit SHA, not @v0
- uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25 # v0.36.0
# pin scanner images by digest
  with:
    image-ref: 'myapp@sha256:...'
```

```bash
trivy image --db-repository ghcr.io/aquasecurity/trivy-db myapp@sha256:...
```

Let Dependabot/Renovate bump the pinned SHA with a version comment so you
still get updates — just reviewed ones.

**When NOT to apply.** Throwaway local ad-hoc scans on a developer
machine can float tags. Anything in CI, or anything with credentials in
scope, pins.

---

## SEC-022 — Sign images with keyless cosign and verify with an explicit identity

**What.** Sign release images in CI with keyless cosign (a short-lived
Fulcio certificate from your OIDC identity, recorded in the Rekor
transparency log), and verify with the **required**
`--certificate-identity` and `--certificate-oidc-issuer` flags. Cosign
≥2.6.0 / ≥3.0.1 targets Rekor v2 (GA late 2025).

**Why.** Docker Content Trust was removed from the Docker CLI in Engine
29, so cosign/Notation are the supported image-signing path. The subtle
footgun is verification: `cosign verify` *without* pinning the identity
and issuer will accept *any* valid keyless signature — including an
attacker's — so the signature proves "someone signed it," not "*we*
signed it." The identity flags are what bind the signature to your CI's
OIDC subject.

**How.**

```bash
# sign in CI (OIDC identity, no long-lived key)
cosign sign ghcr.io/org/app@sha256:...

# verify — identity + issuer are REQUIRED, not optional
cosign verify ghcr.io/org/app@sha256:... \
  --certificate-identity-regexp 'https://github.com/org/.*' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com'
```

**When NOT to apply.** Projects with no supply-chain threat model, or
fully air-gapped builds with no Fulcio/Rekor reachability — there, sign
with a managed key out-of-band instead, but still verify with a pinned
key. Never verify without pinning identity/key.

---

## SEC-023 — Prefer a hardened/minimal verified base for production runtimes

**What.** For production runtime images, prefer a minimal, hardened,
attested base over a full general-purpose distro: Docker Hardened Images
(DHI), Chainguard Images, or a `distroless` base — whichever fits your
toolchain.

**Why.** A slim general base still ships a shell, a package manager, and
dozens of libraries you never call — each a CVE to triage and a tool an
attacker can use post-breach. Hardened bases minimize that surface and
ship the attestations (SLSA provenance, signed SBOMs) that CRA/FedRAMP-
style audits expect, collapsing CVE-triage toil. DHI became free and
Apache-2.0-licensed in late 2025: minimal hardened Debian/Alpine-based
images, non-root by default, with SLSA provenance and signed SBOMs. Their
runtime variants are distroless (no shell or package manager); the `-dev`
variants add those for build stages — so build `FROM` a `-dev` tag and
run on the runtime tag. (Google's `distroless` and Chainguard are
separate options with similar goals.) Complements DOCKER-005 (non-root)
and DOCKER-011 (minimize the final image).

Cite: [Docker Hardened Images](https://docs.docker.com/dhi/),
[use a DHI](https://docs.docker.com/dhi/how-to/use/).

**How.**

```dockerfile
# build in a full image, run on a hardened/minimal one
FROM python:3.13-trixie AS build
# ... build the venv ...

# e.g. a DHI, Chainguard, or distroless runtime
FROM <hardened-base>
COPY --from=build /app/.venv /app/.venv
USER nonroot
ENTRYPOINT ["/app/.venv/bin/python", "-m", "app"]
```

**When NOT to apply.** Images that genuinely need a shell or package
manager at runtime (debugging sidecars, some init containers) — a
distroless/hardened base makes those harder. Dev and CI images also
typically want the full toolchain; this rule is about *production
runtime* images.

---

## SEC-024 — Run the daemon rootless (or with userns-remap) on hosts that run untrusted workloads

**What.** On a host that runs containers you don't fully trust — CI
runners for outside contributors, multi-tenant build hosts, anything
executing third-party images or agent-generated code — run Docker in
[rootless mode](https://docs.docker.com/engine/security/rootless/), or
at least enable [user-namespace remapping](https://docs.docker.com/engine/security/userns-remap/)
(`"userns-remap": "default"` in `daemon.json`).

**Why.** By default a container's root is the host's root, held back
only by capabilities, seccomp and namespaces; a container-escape bug or a
misconfiguration (a privileged flag, a sensitive bind mount) turns into
host root. Rootless mode runs the daemon and containers "as a non-root
user to mitigate potential vulnerabilities in the daemon and the
container runtime." With userns-remap, container root maps to an
unprivileged high UID, so an escaped process "is running as an
unprivileged high-number UID on the host, which does not even map to a
real user."

**How.**

```bash
# rootless: per-user daemon, no root required after install
dockerd-rootless-setuptool.sh install
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
```

Or keep the rootful daemon and remap container root — in
`/etc/docker/daemon.json`:

```json
{ "userns-remap": "default" }
```

Neither replaces DOCKER-005: the image should still run as a non-root
user, so that an app compromise doesn't even get container root.

**When NOT to apply.** Hosts that only run your own trusted images, where
the rootless limitations (no privileged ports below 1024 without setup,
some storage drivers and `--net=host` behaviors differ, bind-mounted
files owned by remapped UIDs) cost more than they protect. Dev
containers and tools that assume the rootful daemon's socket and UID
mapping break under a rootless daemon — keep those on the default
daemon deliberately rather than by accident.

---
