# Python + uv rules

Detailed explanation for each `UV-NNN` rule. These are Python-and-uv-specific
patterns that complement the general Dockerfile rules. They reflect both the
[official uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/)
and hard-won patterns from real codebases.

When a uv rule reinforces or extends a general rule, the cross-reference
is called out. The biggest cross-cuts:

- Multi-stage builds (DOCKER-001)
- Layer ordering (DOCKER-003)
- BuildKit cache mounts (DOCKER-009)
- Digest pinning (DOCKER-002, SEC-010)
- `.venv` in `.dockerignore` (SEC-011)

---

## UV-001 — Install `uv` via `COPY --from=ghcr.io/astral-sh/uv:VERSION@sha256:DIGEST`

**What.** Don't `pip install uv` or `curl | sh` to bootstrap. Use Astral's
distroless uv image as a source stage and copy the binary out:

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /uvx /bin/
```

**Why.** Three reasons:

1. **No bootstrap dependencies.** The distroless uv image contains the static `uv` binary and nothing else — no Python, no shell, no package manager. Copying it doesn't pull in installer dependencies that bloat the build stage.
2. **Cacheable.** `COPY --from=image` is a layer the BuildKit cache can deduplicate across builds, even when manifests change.
3. **Pinnable.** Astral publishes per-version tags and digests. Pin the literal version+digest pair (SEC-010) so the install is reproducible and Renovate can keep the pair updated together.

**How.**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:... AS base

# Astral's uv image is distroless — just the binary
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /uvx /bin/
```

Pin the literal version (`0.11.16`) and digest as a single pair (SEC-010).
Bumping `0.11.16` → `0.5.12` without updating the digest will silently
pull `0.11.16` (the digest wins). Renovate's Dockerfile manager handles
this lockstep if you configure it.

**Multi-arch caveat.** Astral publishes per-architecture digests for
`linux/amd64` and `linux/arm64`. When you build for both architectures
(e.g. `docker buildx build --platform linux/amd64,linux/arm64`), pin
the **manifest list digest** (the top-level `sha256:` shown on the
registry's image overview), not a per-arch digest — otherwise the
non-matching arch silently fails or pulls something stale. If you only
build for one arch, the per-arch digest is fine.

Variant tags exist for people who want uv pre-installed in a fuller
base (`alpine`, `debian`, `debian-slim`,
`python3.9`–`python3.14` × `trixie-slim`/`alpine`, and
`-dhi` for Docker Hardened Images). Note the `bookworm`/`bookworm-slim`
tags were **removed in uv 0.10.0** when the Debian base moved to Trixie
(see UV-011) — use `trixie-slim`. Astral's own
[example repo](https://github.com/astral-sh/uv-docker-example) uses
`ghcr.io/astral-sh/uv:python3.12-trixie-slim` as a *base* (single-stage)
rather than copying out of the distroless image — both forms are
legitimate, with the copy-from-distroless pattern being preferred when
you want strict control over the base layer.

**When NOT to apply.** When you can't reach ghcr.io from your build
runner (air-gapped or restricted CI). Then fall back to the install
script (`curl -fsSL https://astral.sh/uv/install.sh | sh`) — and pin its
version explicitly (`UV_VERSION=0.11.16 sh`).

---

## UV-002 — Two-pass sync: install dependencies first, then the project

**What.** Split `uv sync` into two passes so dependency installation
caches independently of source changes:

1. **Pass 1** — bind-mount `pyproject.toml` and `uv.lock`, run `uv sync --locked --no-install-project`. Installs only external dependencies.
2. **Pass 2** — copy the project source, run `uv sync --locked`. Installs the project itself (editable).

**Why.** Without this split, every source edit invalidates the
dependency-install layer and triggers a full re-resolution + reinstall.
With it, only manifest changes (`pyproject.toml`, `uv.lock`) bust the
dependency layer; source edits only re-run a tiny final-install step.
Typical rebuild time drops from 30–60 s to 1–3 s. This is the canonical
pattern from Astral's [uv-docker-example](https://github.com/astral-sh/uv-docker-example).
Reinforces DOCKER-001 (layer ordering) for the Python ecosystem.

**How.**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:... /uv /uvx /bin/
WORKDIR /app

# Pass 1: external dependencies only.
# Bind-mounts (not COPY) so the manifest files don't end up in the layer.
RUN --mount=type=cache,id=uv-${TARGETARCH:-amd64},target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --no-dev

# Pass 2: project source + editable install.
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN --mount=type=cache,id=uv-${TARGETARCH:-amd64},target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-dev

# put the venv on PATH so `python` is the project's interpreter
ENV PATH="/app/.venv/bin:$PATH"
```

Why `--mount=type=bind` for `pyproject.toml` / `uv.lock` in pass 1: the
files are needed for the install but should not be copied into the layer
(pass 2 copies them properly). Bind mounts make them visible to that
specific `RUN` and nothing else.

**When NOT to apply.** Projects with no dependencies (trivial scripts) —
the split has no benefit. One-stage exploratory Dockerfiles where you
don't care about rebuild speed.

---

## UV-003 — Set `UV_LINK_MODE=copy` when using a BuildKit cache mount

**What.** When the uv cache and the install target (`.venv`) live on
different filesystems — which they do when the cache is a mount and
the venv is in the image's layer FS — set `UV_LINK_MODE=copy` to silence
warnings and avoid cross-filesystem hard-link attempts.

**Why.** uv defaults to hard-linking files from the cache into the venv
to save space. Hard links don't cross filesystems, so when the cache is
mounted from a tmpfs/overlay (BuildKit cache mount) and the venv is on
the image's writable layer, uv falls back to copy *and* prints a warning
on every install. The warning is noisy in CI logs; setting the env var
explicitly avoids it and makes the behavior intentional.

**How.**

```dockerfile
ENV UV_LINK_MODE=copy

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-dev
```

The official guide says: "Changing the `UV_LINK_MODE` silences warnings
about not being able to link files since the cache and sync target are
on separate file systems."

Other valid values: `hardlink` (default, fast but same-filesystem only),
`clone` (reflink — Btrfs/XFS only), `symlink` (rare). `copy` is the safe
default for container builds.

**When NOT to apply.** When the cache mount is on the *same* filesystem
as the venv (rare in containers). When you've placed the venv in an
explicit volume on the same filesystem as the cache (also rare).

---

## UV-004 — Set `UV_COMPILE_BYTECODE=1` for production images

**What.** Compile `.py` files to `.pyc` bytecode at build time so the
runtime doesn't pay the compile cost on first import. Either flag the
sync command or set the env var globally for the build stage.

**Why.** Python compiles source to bytecode on first import and caches
the result. In a fresh container, that compile happens during the
critical first-request window. For cold-start-sensitive workloads
(serverless, scale-to-zero, dev containers), pre-compiling at build time
shaves seconds off startup. Quoting the uv guide: "Compiling Python
source files to bytecode is typically desirable for production images as
it tends to improve startup time (at the cost of increased installation
time and image size)."

**How.** Per-command flag:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --compile-bytecode
```

Or set it once for the stage:

```dockerfile
ENV UV_COMPILE_BYTECODE=1

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev
```

Cost: image is ~10–30% larger (the `.pyc` files), build is 2–5 s slower.
Benefit: cold-start latency drops by hundreds of ms to seconds depending
on dependency tree size.

**When NOT to apply.** Dev images where rebuild speed matters more than
runtime startup. Images built for a single one-shot job where startup
cost amortizes over a long run.

---

## UV-005 — Know the difference between `--locked` and `--frozen`

**What.** Two superficially similar flags:

| Flag | Meaning | When to use |
|---|---|---|
| `--locked` | "Assert that `uv.lock` is up to date with `pyproject.toml`. Fail if not." | Production builds, final sync, and any "this must be reproducible" context. |
| `--frozen` | "Don't even check — just use `uv.lock` as-is." | When you don't have all the inputs uv needs to verify the lock (e.g. pass-1 of a workspace install where workspace member `pyproject.toml` files aren't copied yet). |

**Why.** `--locked` is the safer default — it catches the "you edited
`pyproject.toml` but forgot to refresh `uv.lock`" mistake. `--frozen`
exists for cases where the verification *can't run* (workspaces with
intermediate-layer installs), not because you don't care.

A common mistake: using `--frozen` everywhere because it's faster. That
hides drift between manifest and lock — you can ship images built from
a stale lockfile that doesn't match the manifest.

**How.** Production build, single project:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project
```

Workspace build, intermediate layer (pass 1 only):

```dockerfile
# Pass 1: workspace members not yet copied, so --locked verification can't run.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-workspace

COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/

# Pass 2: all workspace members present, so --locked verification works again.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked
```

**When NOT to apply.** Local dev where you want the lockfile updated as
part of the build (`uv sync` without either flag will refresh it).
Throwaway exploratory builds.

---

## UV-006 — `--no-editable` + copy `/app/.venv` for a minimal final stage

**What.** For production images where you want to ship the smallest
possible runtime, use the "copy-from-builder" pattern: install in a
fat builder stage with `--no-editable`, then copy *only* `/app/.venv`
(not the source) into a clean final stage.

**Why.** `uv sync` defaults to *editable* installs of the project — the
venv contains links back to the source tree at `/app/src/`. That means
the source has to ship in the final image, even though only the venv is
needed at runtime. `--no-editable` makes uv install the project as a
regular wheel into the venv, after which the source is no longer
referenced — you can copy the venv alone into a minimal final stage.

**How.** Multi-stage with copy-from-builder:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:... AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:... /uv /uvx /bin/
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=0
WORKDIR /app

# Pass 1: deps only
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --no-editable --no-dev

# Pass 2: project, non-editable so we don't need source at runtime
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --no-dev

# Final stage: just the venv. No uv, no compiler, no source.
FROM python:3.12-slim@sha256:...
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Non-root user (DOCKER-005)
RUN useradd --system --uid 10001 --no-create-home app
USER 10001

ENTRYPOINT ["python", "-m", "myapp"]
```

Final-stage size: typically 80–120 MB (python:slim + venv), vs 300–500 MB
for the all-in-one form. No build toolchain, no source tree, no uv.

**When NOT to apply.** Dev containers — you *want* the source to be
editable and the env to reflect it. Single-stage images where you've
decided the size hit is acceptable for simplicity.

---

## UV-007 — Use `UV_PROJECT_ENVIRONMENT` / `UV_PYTHON_DOWNLOADS=0` for system-Python builds

**What.** When the base image already provides a Python you trust
(`python:3.12-slim`), tell uv to use *that* Python instead of downloading
its own, and optionally to install into the system site-packages instead
of a `.venv`:

```dockerfile
ENV UV_PYTHON_DOWNLOADS=0
ENV UV_PROJECT_ENVIRONMENT=/usr/local
```

**Why.**

- `UV_PYTHON_DOWNLOADS=0` — uv defaults to downloading and managing its own Python versions. In a Docker stage that already has Python from the base image, this is pure overhead (extra download, extra MB). Setting `0` forces uv to use the system Python.
- `UV_PROJECT_ENVIRONMENT=/usr/local` — uv defaults to creating `.venv/` in the working directory. For minimal final stages, you may want to install directly into the system Python instead, skipping the `PATH="/app/.venv/bin:$PATH"` shim. Mostly useful when copying *into* a fresh final stage.

**⚠️ Destructive footgun.** `uv sync` removes packages from the target
environment that aren't in the lockfile — by design. Astral's docs warn:
*"uv sync will remove extraneous packages from the environment by default
and, as such, may leave the system in a broken state."* When
`UV_PROJECT_ENVIRONMENT=/usr/local`, that **includes system-installed
Python packages** the image's base layer relied on (apt-installed `pip`,
`setuptools`, distribution-managed libraries). On Debian/Ubuntu base
images with apt-installed Python packages, this *will* delete them.

Safe-ish on:

- `python:X.Y-slim` (only `pip`, `setuptools`, `wheel` in site-packages — all replaceable).
- Distroless final stages built from scratch.
- Any image where you fully control what's in the system Python's `site-packages` and don't depend on apt for Python libs.

Dangerous on:

- Stock Debian/Ubuntu base images with `apt-get install python3-*` packages.
- Anything where another tool has installed into `/usr/local` and you'd lose it.

If in doubt: stay with the default `.venv`-in-workspace approach
(UV-002). Use this pattern only when you've consciously chosen to wipe
system site-packages.

**How.** System-Python sync, no `.venv` indirection:

```dockerfile
# safe — python:slim only ships pip/setuptools/wheel in site-packages
FROM python:3.12-slim AS final
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:... /uv /uvx /bin/
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock src/ ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --no-dev

ENTRYPOINT ["python", "-m", "myapp"]
```

Accepted values for `UV_PYTHON_DOWNLOADS`: `automatic` (default),
`manual`, `never`. `0` is accepted as a falsy alias for `never` — both
work.

The combination is especially helpful in distroless final stages where
adding a `.venv` adds path-shimming complexity for no gain.

**When NOT to apply.**

- Debian/Ubuntu/RHEL base images with apt/yum-installed Python packages — `uv sync` will delete them.
- When you specifically want uv-managed Python versions for parity with dev (Astral's uv-managed builds differ slightly from the official `python:` image — same versions, different patches).
- When you want isolation between system Python and project deps. Then prefer the default `.venv`-in-workspace approach (UV-002).

---

## UV-008 — Workspace pattern: `--no-install-workspace` on pass 1, then `--locked` on pass 2

**What.** Astral's [workspaces](https://docs.astral.sh/uv/concepts/workspaces/)
let one repo contain multiple `pyproject.toml` files (members) that share
a single `uv.lock`. The two-pass install (UV-002) needs an extra wrinkle:
pass 1 can't verify the lock (workspace members not yet copied), so use
`--no-install-workspace --frozen` for pass 1 and `--locked` for pass 2.

**Why.** `uv sync --locked` walks the workspace to verify the lockfile
covers every member's dependencies. In pass 1 you've only bind-mounted
the root `pyproject.toml` and `uv.lock`; members aren't there yet, so the
verification fails. `--frozen` skips the verification, letting pass 1
install external dependencies based on the lockfile alone.
`--no-install-workspace` skips trying to install any workspace member
(which would also fail — no source).

**How.**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:... /uv /uvx /bin/
ENV UV_LINK_MODE=copy
WORKDIR /app

# Pass 1: external deps only. Workspace members not present, so --frozen.
RUN --mount=type=cache,id=uv-${TARGETARCH:-amd64},target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-workspace --no-dev

# Pass 2: copy everything, full sync with --locked verification.
COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/
RUN --mount=type=cache,id=uv-${TARGETARCH:-amd64},target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
```

If you want to exclude a *specific* workspace member from sync (e.g. a
dev-only tool), use `--no-install-package <name>` in pass 2.

**When NOT to apply.** Non-workspace projects (single `pyproject.toml`,
no `[tool.uv.workspace]` block) — use UV-002 as written.

---

## UV-009 — Set `UV_TOOL_BIN_DIR=/usr/local/bin` for images that install uv tools

**What.** When a derived image installs CLI tools via `uv tool install`
(ruff, mypy, pre-commit, black, mkdocs, ...), set
`UV_TOOL_BIN_DIR=/usr/local/bin` (or another directory already on
`PATH`) before running the installs. Otherwise uv places the resulting
binaries under `~/.local/bin/uv-tools/` — which isn't on `PATH` in
most base images, so the tools install successfully but aren't
findable.

```dockerfile
# syntax=docker/dockerfile:1
ENV UV_TOOL_BIN_DIR=/usr/local/bin

RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install ruff && \
    uv tool install mypy && \
    uv tool install pre-commit
```

After these `RUN`s, `ruff`, `mypy`, and `pre-commit` are immediately
runnable in subsequent stages, by the entrypoint, or by `docker exec`.

**Why.** `uv tool install` is the right primitive for "install a CLI
tool in its own isolated venv" — each tool gets its own environment so
its deps don't conflict with the project's. uv tracks tool installs in
a dedicated directory (`uv tool dir`, default `~/.local/share/uv/tools`)
and symlinks the entry-point binaries into a bin directory.

The default `~/.local/bin/uv-tools/` works on developer laptops where
the shell adds `~/.local/bin` to `PATH` automatically (or via
`uv tool update-shell`). Inside a container, three things break:

1. **`PATH` doesn't include `~/.local/bin` in most base images.** `python:slim`, `mcr.microsoft.com/devcontainers/*`, distroless — none of them have it. So `RUN uv tool install ruff` followed by `RUN ruff check .` fails with `ruff: command not found`.
2. **`HOME` varies by user.** During `RUN`, `HOME` is `/root` (root user). After `USER 10001`, `HOME` may be unset or `/`. The "where did `uv tool install` put it?" question becomes confusing.
3. **Layering across users.** If the tool was installed as root but the final stage runs as a non-root user, `~/.local/bin` for root isn't on the non-root user's `PATH` regardless.

Setting `UV_TOOL_BIN_DIR=/usr/local/bin` (or `/opt/bin`, or any
directory already on the default `PATH`) sidesteps all three: the tool
binaries land somewhere every user can find them.

Cite: [uv guide — using uv tool install in Docker](https://docs.astral.sh/uv/guides/integration/docker/),
[uv reference — UV_TOOL_BIN_DIR](https://docs.astral.sh/uv/reference/environment/#uv_tool_bin_dir).

**How.** Common patterns:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:... /uv /uvx /bin/

# Install CLI tools so they land on PATH for every subsequent stage
ENV UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_TOOL_DIR=/opt/uv-tools \
    UV_PYTHON_DOWNLOADS=0

RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install --python 3.12 ruff && \
    uv tool install --python 3.12 mypy && \
    uv tool install --python 3.12 pre-commit
```

`UV_TOOL_DIR` (separate from `UV_TOOL_BIN_DIR`) controls where the
tool venvs themselves live — set it to a path you can `chown` to your
container user if needed, or leave it at the default.

For dev containers that share tools across worktrees, combine with a
named-volume mount so the tools survive rebuilds:

```jsonc
// devcontainer.json
{
  "image": "myorg/python-dev:latest",
  "containerEnv": {
    "UV_TOOL_BIN_DIR": "/usr/local/bin",
    "UV_TOOL_DIR":     "/opt/uv-tools"
  },
  "mounts": [
    "source=myrepo-uv-tools,target=/opt/uv-tools,type=volume"
  ]
}
```

For final-stage images that need the tools available to a non-root
user, install during the builder stage *or* `chown` the bin directory
after install:

```dockerfile
FROM python:3.12-slim AS final
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:... /uv /uvx /bin/

RUN useradd --system --uid 10001 --create-home app

ENV UV_TOOL_BIN_DIR=/usr/local/bin
RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install ruff
# /usr/local/bin is already on PATH for every user; no extra wiring needed

USER 10001
ENTRYPOINT ["ruff", "check"]
```

**When NOT to apply.**

- Images that don't use `uv tool install` at all — the env var has no effect.
- Cases where the default `~/.local/bin/uv-tools/` is genuinely what you want, e.g. you've explicitly added that path to the image's `PATH` and want strong scoping per user. (Rare in containers, common on dev laptops.)
- Single-stage dev containers where you `uv tool install` interactively and rely on `uv tool update-shell` having been run — but for *image*-built tool installs, prefer the explicit `UV_TOOL_BIN_DIR` declaration over relying on shell rc state.
## UV-010 — Use `ENV UV_NO_DEV=1` and `UV_NO_INSTALL_*` instead of repeating flags

**What.** Since uv 0.8.7, `UV_NO_DEV=1` is a first-class environment
variable (the official Docker guide now leads with it), and
`UV_NO_INSTALL_PROJECT` / `UV_NO_INSTALL_WORKSPACE` (uv 0.11.20) express
the two-pass split (UV-002 / UV-008) via env rather than per-command
flags.

**Why.** Repeating `--no-dev` / `--no-install-project` on every `uv sync`
invocation across a multi-stage Dockerfile is easy to get out of sync
between the dependency pass and the source pass — one drifts and you
either ship dev deps or fail to install the project. Setting the env once
in the stage keeps both passes consistent.

**How.**

```dockerfile
ENV UV_NO_DEV=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project
COPY . /app
RUN uv sync --locked
```

**When NOT to apply.** Multi-target Dockerfiles that build both a
test/dev image (needs dev deps) and a production image from shared stages
— there, set the env per-stage or keep explicit per-command flags so the
test stage still gets dev dependencies.

---

## UV-011 — Migrate off the removed `bookworm` uv base tags to `trixie`

**What.** uv 0.10.0 removed the `bookworm` / `bookworm-slim` image tags
when the Debian base moved to Trixie (Debian 13). Pinned references to
`ghcr.io/astral-sh/uv:python3.X-bookworm-slim` no longer resolve on
current uv image tags — use the `trixie-slim` variant.

**Why.** A Dockerfile pinning a `bookworm` uv tag silently breaks the day
it can no longer pull that tag (or keeps building from a stale cached
layer while the rest of the ecosystem moves to Trixie). The Alpine line
similarly moved to 3.22+; Python 3.8 base variants were dropped.

**How.**

```dockerfile
# before: FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim
```

If you copy the binary out of the distroless image (UV-001), only the
version+digest pin matters — this rule is about the *base-image* variant
tags.

**When NOT to apply.** Images deliberately pinned to an older uv release
by digest that still publishes `bookworm` — but new pulls and upgrades
will hit the removal, so plan the move.

---
