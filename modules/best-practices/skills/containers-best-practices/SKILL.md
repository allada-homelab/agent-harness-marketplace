---
name: containers-best-practices
description: Use when working with Dockerfiles, docker-compose/compose.yml, buildx, dev containers (devcontainer.json), or .dockerignore — including Python container builds with uv. Covers image hardening, multi-stage builds, layer/cache ordering, BuildKit cache + secret mounts, compose services, GPU + Docker Model Runner, dev-container lifecycle and volume state, and container security footguns. For Python packaging outside containers use python-best-practices or uv-best-practices.
---

# Container best practices

A curated rule set for Dockerfiles (both app images and dev container images),
`docker-compose`/`compose.yml`, and `devcontainer.json`. Each rule has a stable
ID and a one-line summary. The full **What / Why / How / When-not-to-apply**
explanation lives in the `references/` files — pull only the section you need.

## When to apply this skill

Activate when any of these are true:

- The conversation involves Docker, container images, dev containers, or `docker-compose`.
- The user is editing or generating a `Dockerfile`, `*.dockerfile`, `devcontainer.json`, `compose.yml`, `compose.yaml`, `docker-compose.yml`, `docker-compose.yaml`, or `.dockerignore`.
- The user asks to scaffold a new repo that will need containers.
- The user asks about container image hardening, buildx, build checks, GPU compose services, Docker Model Runner, or Python container builds with uv.
- The `containers-audit` skill is invoked.

## Coverage

Topics the rule index below covers, for matching against the task at hand:

- **Dockerfile authoring** — multi-stage builds, layer ordering, non-root users, signal handling / PID 1, healthchecks, `# syntax=docker/dockerfile:1` pin, HereDoc + `pipefail`, `COPY --exclude` / `--parents` / `--link`, `WORKDIR`, exec-form `ENTRYPOINT`/`CMD`.
- **BuildKit & buildx** — `RUN --mount=type=cache|secret|ssh`, cache backends (gha / registry / inline / local), `--load` vs `--push`, `docker buildx bake`, builder drivers, `docker buildx debug build`, `docker buildx build --check` lint, reproducible builds (`SOURCE_DATE_EPOCH` + `rewrite-timestamp`), SBOM + provenance attestations and their registry-compatibility caveats.
- **Compose** — service dependencies, `secrets:`, `develop.watch`, `configs:`, `include:`, `gpus:`, `models:` (Docker Model Runner).
- **Dev containers** — lifecycle hook choice, named-volume strategy, agentic CLI tool state (Claude / Codex / `gh`) in per-worktree volumes rather than host bind mounts, `runArgs` / capabilities / `init`, declarative `secrets` property, `devcontainer-lock.json`, `hostRequirements.gpu`, SSH agent + known_hosts + git credentials, `containerEnv` vs `remoteEnv`, editor-vs-CLI parity, Docker socket risk, base-image tag pinning.
- **Python in containers (uv)** — two-pass sync, `--locked` vs `--frozen`, `UV_COMPILE_BYTECODE`, `UV_TOOL_BIN_DIR` for tool installs.
- **Package managers** — `apt-get update`+`install` pairing, `--no-install-recommends`, `pip --no-cache-dir`, APT cache mount caveats.
- **Security & hygiene** — secret-shaped `ARG`/`ENV` detection, rootless / userns-remap daemons, `COPY .env` / `COPY .git` bans, `ADD <url>` checksum requirement, `curl | sh` checksum verification, `chmod 777` detection, `no-new-privileges`, image pinning by digest, `.dockerignore` existence *and* coverage, `.gitignore` checks for `.env`, OCI image labels, `MAINTAINER` deprecation, `EXPOSE`/`CMD` port agreement, json-file log rotation.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply to the current file.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user (e.g. "Switching to a non-root user — DOCKER-005").

## Rules — Dockerfile authoring

See [`references/dockerfile.md`](./references/dockerfile.md).

- **DOCKER-001** — Use multi-stage builds for any compiled or dependency-heavy app.
- **DOCKER-002** — Pin base images by digest (`image@sha256:...`), not just tag.
- **DOCKER-003** — Order layers cache-friendly: dependency manifests first, source last.
- **DOCKER-004** — `COPY` only what's needed; rely on `.dockerignore` to keep context small.
- **DOCKER-005** — Run as a non-root user in the final stage.
- **DOCKER-006** — Use `tini`/`dumb-init` (or run with `--init`) for proper PID 1 / signal handling.
- **DOCKER-007** — Add `HEALTHCHECK` for long-lived services.
- **DOCKER-009** — Use `RUN --mount=type=cache` for package managers under BuildKit.
- **DOCKER-010** — Never bake secrets into layers; use `RUN --mount=type=secret`.
- **DOCKER-011** — Minimize the final image: distroless / alpine / slim — choose with eyes open.
- **DOCKER-012** — Set `WORKDIR` explicitly; never rely on `/`.
- **DOCKER-013** — Prefer `ENTRYPOINT` (exec form) + `CMD` over shell-form commands.
- **DOCKER-014** — Use HereDoc syntax (`RUN <<EOF ... EOF`) for multi-line `RUN` blocks.
- **DOCKER-015** — Use `set -o pipefail` (or exec-form bash) for piped `RUN` commands.
- **DOCKER-016** — Prefer `COPY --link` for COPYs that don't depend on prior `RUN` mutations — produces independent overlay layers that survive base-image rebases. `--link` is per-instruction, not a stage-wide rule.
- **DOCKER-017** — Scope BuildKit cache mount `id=` by `${TARGETARCH}` for multi-platform builds.
- **DOCKER-018** — Remove the `docker-clean` snippet from the image's apt.conf.d before mounting an APT cache (otherwise the cache is silently wiped after every install).
- **DOCKER-019** — `apt-get update` and `apt-get install` must share a single `RUN` — split layers cache the package index separately and serve stale data on rebuild.
- **DOCKER-020** — Pass `--no-install-recommends` to `apt-get install` (and the RHEL `--setopt=install_weak_deps=False` equivalent) — recommends pull in tens of MB of unneeded packages.
- **DOCKER-021** — `pip install` either takes `--no-cache-dir` or wraps in a BuildKit cache mount; the default wheel cache bloats the layer by hundreds of MB.
- **DOCKER-022** — Replace deprecated `MAINTAINER` with `LABEL org.opencontainers.image.authors=...` / `.vendor=...`.
- **DOCKER-023** — Declare OCI image labels (`org.opencontainers.image.source`, `.revision`, `.version`, `.created`, `.licenses`) for traceability from registry back to git SHA.
- **DOCKER-024** — Avoid `chmod 777` / `chmod -R 777`; almost always masks a UID mismatch that wants `chown` instead.
- **DOCKER-025** — `EXPOSE` must agree with the port `CMD`/`ENTRYPOINT` actually binds; drift breaks `docker run -P`, compose `expose:`, and reverse-proxy auto-discovery.
- **DOCKER-026** — Never `curl ... | sh` without checksum verification — fetch remote artifacts with `ADD --checksum=sha256:...` (Dockerfile ≥1.6) or verify `sha256sum` before executing.
- **DOCKER-027** — Pin `# syntax=docker/dockerfile:1` at the top of every Dockerfile; without it, BuildKit features silently degrade. Don't pin an older minor like `:1.8` — that's a downgrade.
- **DOCKER-028** — Use `COPY --exclude=<pattern>` (Dockerfile ≥1.19) to filter unwanted files from multi-file copies instead of `COPY` + `RUN rm` or multi-COPY workarounds.
- **DOCKER-029** — Run `docker build --check` as a Dockerfile lint step in CI (Buildx ≥0.15, Dockerfile ≥1.8); it exits non-zero on violations, and `# check=error=true` fails ordinary builds too.
- **DOCKER-030** — Make image builds bit-for-bit reproducible via `SOURCE_DATE_EPOCH` + `--output type=image,...,rewrite-timestamp=true` (BuildKit ≥0.13).
- **DOCKER-031** — Use `COPY --parents` (Dockerfile ≥1.20) to preserve source directory structure instead of flattening or post-copy `mkdir`.
- **DOCKER-032** — Cap heavy `RUN` steps with build-time resource limits (`--resource cpu=,memory=`) on shared builders.
- **DOCKER-033** — Pin `RUN --network=none` on steps that must not touch the network, to enforce reproducibility.

## Rules — Dev containers

See [`references/devcontainer.md`](./references/devcontainer.md).

- **DEVC-001** — Map host UID/GID to avoid file-ownership pain on bind mounts (`updateRemoteUserUID`; it skips taken UIDs, is off on macOS, and only re-owns `$HOME`).
- **DEVC-002** — Put long-running installs in the **image**, not `postCreateCommand`.
- **DEVC-003** — Use official `features` for common tooling instead of hand-rolling; `:1` pins the feature major, the `version` option is the tool version.
- **DEVC-004** — Pick the right lifecycle hook: `onCreateCommand` vs `updateContentCommand` vs `postCreateCommand` vs `postStartCommand` vs `postAttachCommand`.
- **DEVC-005** — Mount cache volumes for language package managers (uv, pnpm, go module cache, cargo, pip).
- **DEVC-006** — Be deliberate about `mounts` and `workspaceFolder` — never mount key files or credential dirs; SSH goes through the agent (DEVC-019).
- **DEVC-007** — Choose `remoteUser` vs `containerUser` consciously; on images that supply a non-root user (mcr devcontainers images do it via their metadata label) set neither.
- **DEVC-008** — Don't commit secrets in `devcontainer.json`; use `${localEnv:...}` or a mounted env file.
- **DEVC-009** — Declare required `customizations.vscode.extensions` and settings the project assumes.
- **DEVC-010** — Lifecycle scripts must be idempotent (they re-run on rebuild).
- **DEVC-011** — Prefer `image` or `build` + a pinned base; avoid bare `Dockerfile` references that resolve ambiguously.
- **DEVC-012** — Cross-platform host mount paths use `${localEnv:HOME}${localEnv:USERPROFILE}`; an empty or missing bind source is a hard mount error, and `${localEnv:VAR:default}` covers only an unset variable.
- **DEVC-013** — Two-tier named volume naming: `<repo>-<tool>` for shared caches, `<repo>-<purpose>-${devcontainerId}` for per-worktree state (`.venv`, history, tool auth).
- **DEVC-014** — On macOS, mount `.venv` (and other heavy tool-generated dirs) as a named volume — bind-mounted Python venvs are dramatically slower through VirtioFS. On Linux too when host and container both run uv: a shared venv symlinks an interpreter missing on the other side, so each side deletes and rebuilds it.
- **DEVC-015** — Persist agentic CLI tool state (the home-directory `.claude`, `.codex`, `.config/gh` dirs, etc.) in per-worktree named volumes. Don't bind-mount these from the host — leaks tokens and conversation history both directions. Don't omit the mount — every rebuild wipes login state.
- **DEVC-016** — Use `forwardPorts` + `portsAttributes` for editor port forwarding, but the devcontainer CLI ignores them — use `appPort` (published on `127.0.0.1`) for headless use; `runArgs` only for flags the spec doesn't model.
- **DEVC-017** — Add capabilities deliberately via the first-class `capAdd` / `securityOpt` properties (they also reach compose, unlike `runArgs`); never default to `privileged`.
- **DEVC-018** — Set `"init": true` at the devcontainer.json level (or `services.<x>.init: true` in compose) so signals + zombie reaping work — same DOCKER-006 rationale, but at the dev-container layer.
- **DEVC-019** — SSH and git credentials: bind the host ssh-agent socket (the CLI never forwards it), never key files or the host SSH dir; pin known_hosts; strip credential helpers and host pagers from a copied gitconfig.
- **DEVC-020** — Use the top-level `secrets` property to declare *recommended* secret names (Codespaces offers an optional prompt; the devcontainer CLI ignores it); `--secrets-file` feeds lifecycle commands only.
- **DEVC-021** — Commit `devcontainer-lock.json` (stable, generated by default in CLI ≥0.87.0) for reproducible feature versions; use `--frozen-lockfile` in CI.
- **DEVC-022** — Declare `hostRequirements.gpu` for GPU dev containers; don't hard-code `runArgs --gpus all` (the CLI adds it when it detects a GPU).
- **DEVC-023** — `containerEnv` reaches every process (`docker exec`, agents); `remoteEnv` only tool-spawned ones; `${containerEnv:VAR}` is valid only in `remoteEnv`.
- **DEVC-024** — Configs started headless (CLI, CI, agents) must do what VS Code does for you: agent forwarding, gitconfig, known_hosts, port forwarding, GPG.
- **DEVC-025** — A Docker socket (docker-outside-of-docker) is root on the host — every credential boundary is moot with it, especially with auto-approve agents; make it an explicit, documented choice.
- **DEVC-026** — Pin mcr dev container images to `<image-major>-<lang>-<os>` (e.g. `python:3-3.14-trixie`) or a digest; short tags float across image majors and OS releases, which breaks features.

## Rules — docker-compose

See [`references/compose.md`](./references/compose.md).

- **COMPOSE-001** — Use `depends_on` with `condition: service_healthy`, not bare `depends_on`; add `restart: true` (≥2.17) to restart on dependency updates and `required: false` (≥2.20) for optional dependencies.
- **COMPOSE-002** — Pick named volumes vs bind mounts deliberately; know when each is correct.
- **COMPOSE-003** — Use `env_file` instead of inline `environment` for secrets-adjacent values.
- **COMPOSE-004** — Gate optional services with `profiles` (tools, debug, monitoring).
- **COMPOSE-005** — Use `compose.override.yml` for local-only overrides; `.gitignore` it.
- **COMPOSE-006** — Compose v2 ignores the top-level `version:` key — remove it from new files.
- **COMPOSE-007** — Define explicit `networks` for multi-service apps; don't rely on the default bridge for everything.
- **COMPOSE-009** — Use `restart: unless-stopped` for long-lived services; it differs from `always` only in keeping a manually stopped container stopped across a daemon restart.
- **COMPOSE-010** — Use YAML anchors / `extends` instead of duplicating service definitions.
- **COMPOSE-011** — Healthchecks belong on the services that need to be waited on, not the waiters.
- **COMPOSE-012** — One-shot init/migration containers use `restart: "no"` and downstream services depend on them with `condition: service_completed_successfully`; `docker compose up` re-runs them every time, so they must be idempotent.
- **COMPOSE-013** — Postgres: mount the data volume at `/var/lib/postgresql/data` for ≤17 and at `/var/lib/postgresql` for 18+ (version-qualified `PGDATA`); the wrong level silently writes to an anonymous volume.
- **COMPOSE-014** — Reverse-proxy healthchecks hit a *local* endpoint (e.g. nginx `location = /__healthz`), not a path that proxies upstream — otherwise backend slowness restarts the proxy.
- **COMPOSE-015** — Use `develop.watch` (Compose ≥ 2.22) for hot-reload — `sync` / `rebuild` / `restart` / `sync+restart` / `sync+exec` per path, plus `initial_sync`, beats bare bind-mounting the workspace.
- **COMPOSE-016** — Use the top-level `configs:` block for non-secret config files; pairs cleanly with `secrets:` (SEC-009) and avoids the "single-file bind mount becomes a directory" footgun.
- **COMPOSE-017** — Set `pull_policy` explicitly on shared / production stacks; the default `missing` silently runs stale images for mutable tags other than `latest` (which is always pulled). `daily` / `weekly` / `every_<duration>` sit in between.
- **COMPOSE-018** — Know the two unrelated `.env` mechanisms: project-dir `.env` (parse-time `${VAR}` substitution into compose.yml) vs `env_file:` (runtime container env). `--env-file` only affects the first.
- **COMPOSE-019** — Use the `include:` directive (Compose ≥2.20) to compose modular sub-applications into a parent project; distinct from `extends:` (single-service) and `-f` (file-level merge). Remote `oci://` sources need Compose ≥2.34 (and COMPOSE-028).
- **COMPOSE-020** — Use the `gpus:` shorthand (Compose ≥2.30) for GPU services; replaces the verbose `deploy.resources.reservations.devices` form.
- **COMPOSE-021** — Use the top-level `models:` block (Compose ≥2.38) for declarative AI-model dependencies via Docker Model Runner (Docker Engine or Desktop); `<KEY>_URL` / `<KEY>_MODEL` injected as env vars.
- **COMPOSE-023** — Set `security_opt: ["no-new-privileges:true"]` on production services; closes the setuid-escalation path that DOCKER-005 alone doesn't.
- **COMPOSE-026** — Declare `logging:` on long-lived services — prefer the `local` driver (rotates by default); on `json-file` set `max-size` + `max-file`, since it has no size limit and silently fills the host disk.
- **COMPOSE-027** — Use `post_start` / `pre_stop` lifecycle hooks (Compose ≥2.30) for privileged setup/teardown without weakening the service.
- **COMPOSE-028** — Require Compose ≥2.40.2 (or v5) before resolving any remote OCI compose artifact (`include: oci://`, `-f oci://`) — CVE-2025-62725 path-traversal via artifact layer annotations.
- **COMPOSE-029** — Set `init: true` on services whose image runs the app as PID 1 without an init — signals get forwarded and zombies reaped; doesn't replace DOCKER-006 for images you build.

## Rules — Buildx & cache backends

See [`references/buildx.md`](./references/buildx.md). Pairs with the
BuildKit-side rules under "Dockerfile authoring" (DOCKER-009, 010, 017)
and "Security & build" (SEC-002, 004, 006).

- **BUILDX-001** — Pick a cache backend per scenario: `gha` for GitHub Actions, `registry` for portable CI, `inline` for simplest-but-limited, `local` for single-machine.
- **BUILDX-002** — Cache reuse requires **both** `--cache-from` and `--cache-to`. Specify `--cache-from` multiple times (branch + main fallback). Use `mode=max` for multi-stage builds where intermediate layers matter.
- **BUILDX-003** — Choose `--load` (single-arch, into local daemon), `--push` (registry, multi-arch OK), or `--output type=...` (OCI archive, local dir). Without one of these, multi-arch builds run and **discard** the result.
- **BUILDX-004** — Use `docker buildx bake` for multi-target / declarative builds — replaces long CLI commands, reads `compose.yaml` directly, builds all targets in parallel.
- **BUILDX-005** — The default `docker` driver exports caches and builds multi-platform images only with the containerd image store, and never exports tarballs. Switch to `docker-container` (or `kubernetes`) for full BuildKit features. `setup-buildx-action` does this for you in CI.
- **BUILDX-006** — For non-trivial multi-arch builds, use native runners per architecture (multi-node builder, or separate CI jobs + `imagetools create`). QEMU emulation is much slower for CPU-bound builds.
- **BUILDX-007** — Use `docker buildx debug build` (still experimental) — or `docker buildx dap build` (out of experimental since buildx v0.33.0) for editor integration — for interactive step-through of failing builds; replaces the `RUN sleep 999` + `docker exec` hack.
- **BUILDX-008** — Min-mode provenance is attached by default and already makes the push an index; registries that can't store one need `--provenance=false` / `BUILDX_NO_DEFAULT_ATTESTATIONS=1`, not `mode=min`. `mode=max` records build-arg values.
- **BUILDX-009** — Use `bake` matrix targets + composable HCL attributes for multi-variant builds.
- **BUILDX-010** — Pin the Docker GitHub Actions (`setup-buildx-action@v4`, `build-push-action@v7`, `bake-action@v7`) by commit SHA.

## Rules — Security & build

See [`references/security-build.md`](./references/security-build.md).

- **SEC-001** — Always have a `.dockerignore`. At minimum: `.git`, `node_modules`, `__pycache__`, `.venv`, `.env*`, `dist/`, build artifacts.
- **SEC-002** — Use BuildKit (the default builder since Docker Engine 23.0, or `docker buildx`). Many modern features depend on it.
- **SEC-004** — Build multi-platform with `buildx` only when needed; single-platform is cheaper.
- **SEC-005** — Never leak `.git`, lockfile-only artifacts, or `node_modules` into images.
- **SEC-006** — Use BuildKit secret mounts for build-time credentials (`env=` exposes one as a variable, Dockerfile ≥1.10); never `ARG` them — build args persist in image history and provenance.
- **SEC-008** — Minimize `RUN` layers without sacrificing readability; combine related steps, not unrelated ones.
- **SEC-009** — Use Compose's `secrets:` block (mounted as files under `/run/secrets/`) instead of `environment:` for any sensitive value — env vars leak via `docker inspect`, `/proc/<pid>/environ`, and logs. `file:` secrets are world-readable `0444` bind mounts; `uid`/`gid`/`mode` are ignored for them.
- **SEC-010** — Image references with `@sha256:` digest must be fully literal; don't templatize the digest in Jinja/copier (template drift makes the version+digest pair inconsistent) and don't split version + digest across separate variables. A template's version choices are each a complete literal `image:tag@sha256` string kept current by Renovate.
- **SEC-011** — Add `.venv`, `node_modules`, `target/`, `.gradle/`, tool caches and other platform-specific build dirs to `.dockerignore` — they're at best slow, at worst architecture-incompatible inside the image.
- **SEC-012** — Never `COPY .env` / `COPY *.env` into images; explicit `COPY` bypasses `.dockerignore` and bakes secrets into a layer permanently.
- **SEC-013** — `.git/` must be in `.dockerignore` and never `COPY`'d into the final image — leaks full repo history, rotated secrets, internal codenames.
- **SEC-014** — Flag `ARG`/`ENV` names matching `*SECRET*` / `*TOKEN*` / `*PASSWORD*` / `*KEY*` / `*CREDENTIAL*` — values get baked into image metadata visible via `docker history` / `docker inspect`.
- **SEC-015** — `.dockerignore` must be *comprehensive*, not just present; check coverage against a baseline (VCS, secrets, per-ecosystem build dirs, tool caches, editor/OS, Docker meta).
- **SEC-016** — Broad `COPY . .` is only safe when `.dockerignore` passes SEC-015; without comprehensive ignores, prefer narrow per-subtree copies.
- **SEC-017** — Prefer `COPY` over `ADD`; flag only un-checksummed `ADD <url>` (silent supply chain) and implicit local tar auto-extract. `ADD --checksum=` is the recommended remote fetch.
- **SEC-019** — `.env` files must be in `.gitignore` (not only `.dockerignore`) *and* must not already be git-tracked — `git rm --cached` is required to actually untrack a previously-committed `.env`.
- **SEC-020** — Use `RUN --mount=type=ssh` (or `ADD git@...`) + `docker buildx build --ssh default` for SSH-authenticated git/dep access during builds, or a host-scoped `GIT_AUTH_TOKEN.<host>` secret for HTTPS; never `COPY id_rsa` or `ARG SSH_PRIVATE_KEY`.
- **SEC-021** — Pin third-party scanner/tool images by digest and CI Actions by commit SHA — floating tags get hijacked (Trivy supply-chain compromise, CVE-2026-33634).
- **SEC-022** — Sign images with keyless cosign and verify with explicit `--certificate-identity` + `--certificate-oidc-issuer` (Docker Content Trust was removed in Engine 29).
- **SEC-023** — Prefer a hardened/minimal verified base (Docker Hardened Images — Apache-2.0, distroless runtime variants — Chainguard, distroless) for production runtimes.
- **SEC-024** — Run the daemon rootless (or with userns-remap) on hosts that run untrusted workloads; neither replaces DOCKER-005.

## Rules — Python + uv

See [`references/uv-python.md`](./references/uv-python.md). Apply alongside
the general Dockerfile rules above (especially DOCKER-001, 002, 003, 009,
and SEC-010, SEC-011).

- **UV-001** — Install `uv` via `COPY --from=ghcr.io/astral-sh/uv:VERSION@sha256:DIGEST /uv /uvx /bin/`. Pin the literal version+digest pair (SEC-010) and verify it with `gh attestation verify`; the uv image is distroless, so the copy carries no extra weight.
- **UV-002** — Two-pass sync: bind-mount manifests + `uv sync --locked --no-install-project` first; then copy source + `uv sync --locked`. Dependency layer caches independently from source edits. Declare `ARG TARGETARCH` in the stage before using it in a cache `id=`.
- **UV-003** — Set `ENV UV_LINK_MODE=copy` whenever a BuildKit cache mount is used — silences the cross-filesystem hard-link warning that fires on every install otherwise.
- **UV-004** — Set `ENV UV_COMPILE_BYTECODE=1` (or pass `--compile-bytecode`) for production images; trades a bit of build time for noticeably faster cold starts.
- **UV-005** — `--locked` asserts the lockfile is up to date with `pyproject.toml`; `--frozen` skips that check. Default to `--locked` everywhere; use `--frozen` only in workspace pass-1 where members aren't yet present.
- **UV-006** — For minimal final images, use the copy-from-builder pattern: install with `--no-editable` in a builder stage, then `COPY --from=builder /app/.venv /app/.venv` into a clean final stage — source doesn't ship.
- **UV-007** — Set `UV_PYTHON_DOWNLOADS=0` (use the base image's Python, don't download another) and optionally `UV_PROJECT_ENVIRONMENT` pointed at the system prefix (install into system Python, skip the `.venv` indirection) for system-Python builds.
- **UV-008** — Workspace pattern: pass 1 uses `uv sync --frozen --no-install-workspace` (members not yet copied), pass 2 uses `uv sync --locked` after the source is in place.
- **UV-009** — Point `UV_TOOL_BIN_DIR` at the system bin dir for derived images that install CLI tools via `uv tool install`, so the binaries land on `PATH` instead of uv's default executable dir (`$HOME/.local/bin`).
- **UV-010** — Use `ENV UV_NO_DEV=1` and the `UV_NO_INSTALL_*` env vars instead of repeating flags across the two-pass sync.
- **UV-011** — Migrate off the removed `bookworm` uv base tags to `trixie` (uv 0.10.0 dropped `bookworm`/`bookworm-slim`).

## Reference file structure

Every rule in every `references/` file follows the same shape:

- **What** — the rule, restated precisely.
- **Why** — a concrete failure mode if you violate it (real footgun, not theory).
- **How** — a minimal correct snippet.
- **When NOT to apply** — exceptions and tradeoffs.

When citing a rule in a response or PR, give the rule ID and a one-line
summary; expand only if the user asks for the rationale.
