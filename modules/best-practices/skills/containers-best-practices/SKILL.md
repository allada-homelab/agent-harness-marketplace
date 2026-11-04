---
name: containers-best-practices
description: Use when working with Dockerfiles, docker-compose/compose.yml, buildx, dev containers (devcontainer.json), or .dockerignore — including Python container builds with uv. Covers image hardening, multi-stage builds, layer/cache ordering, BuildKit cache + secret mounts, compose services, GPU + Docker Model Runner, dev-container lifecycle and volume state, and container security footguns. For Python packaging outside containers use python-best-practices or uv-best-practices.
user-invocable: false
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

## Applicability

Rules with no `when:` tag apply to any repository with container files. A
tagged rule applies only when its tag's check matches the repository. To
audit a repo, run each check once, then read the untagged rules plus the
rules whose tag matched.

| Tag | Applies when | Detect |
|---|---|---|
| `dockerfile` | The repo has a Dockerfile | `git ls-files \| grep -iE '(^\|/)(Dockerfile[^/]*\|[^/]*\.dockerfile\|Containerfile)$'` |
| `cache-mount` | A Dockerfile uses BuildKit cache mounts | `git grep -l 'mount=type=cache' -- '*Dockerfile*' '*.dockerfile' '*Containerfile*'` |
| `build-secrets` | The build consumes secrets or SSH | `git grep -lE 'mount=type=(secret\|ssh)\|--secret[ =]\|--ssh[ =]\|GIT_AUTH_(TOKEN\|HEADER)'` |
| `compose` | The repo has a Compose file | `git ls-files \| grep -iE '(^\|/)(docker-)?compose[^/]*\.ya?ml$'` |
| `devcontainer` | The repo has a dev container | `git ls-files \| grep -E '(^\|/)\.devcontainer(/[^/]+)*/devcontainer\.json$\|(^\|/)\.devcontainer\.json$'` |
| `uv` | An image or Compose service uses uv | `git grep -lE 'astral-sh/uv\|uv (sync\|pip\|tool)' -- '*Dockerfile*' '*.dockerfile' '*compose*.y*ml'` |
| `ci-build` | CI or scripts build or push images | `git grep -lE 'docker/(build-push\|setup-buildx\|bake\|login\|metadata)-action\|docker (buildx )?(build\|bake\|push)' -- .github/workflows .gitlab-ci.yml scripts Makefile justfile` |
| `cache-export` | A build exports its cache | `git grep -lE -- '--cache-to\|cache-to:\|cache_to:' -- .github .gitlab-ci.yml '*bake*' '*compose*.y*ml' scripts Makefile justfile` |
| `multi-platform` | Images are built for more than one platform | `git grep -lE -- '(--platform[ =]\|platforms:).*(linux/[a-z0-9/]+,\|\[.*,)' -- .github .gitlab-ci.yml '*bake*' '*compose*.y*ml' scripts Makefile justfile` |
| `attestations` | Builds attach SBOM or provenance | `git grep -lE -- '--(sbom\|provenance\|attest)\b\|^\s*(sbom\|provenance\|attest):' -- .github .gitlab-ci.yml '*bake*' scripts Makefile justfile` |
| `docker-host` | The repo configures a Docker daemon | `git ls-files \| grep -E '(^\|/)daemon\.json$'`, or `git grep -lE 'userns-remap\|dockerd-rootless'` |

Rules were last checked on 2026-11-03 against docker/docs main (d40e4d2),
devcontainers/spec main (c95ffee) and uv 0.13.7 (316c827), with live runs on
Docker Engine 29.9.0, Buildx 0.38.0 and Compose 5.6.0, by the `rules-sweep`
command in the `best-practices-maintainer` module; a new sweep starts from
those commits.

## Rules — Dockerfile authoring

See [`references/dockerfile.md`](./references/dockerfile.md).

- **DOCKER-001** — Use multi-stage builds for any compiled or dependency-heavy app. _(when: dockerfile)_
- **DOCKER-039** — Name build stages (`FROM … AS build`) and `COPY --from=build` by name; `COPY --from=0` silently points at another stage when stages are added or reordered. _(when: dockerfile)_
- **DOCKER-002** — Pin base images by digest (`image@sha256:...`), not just tag, and pair every pin with a bot that updates the digest and with scheduled rebuilds. _(when: dockerfile)_
- **DOCKER-003** — Order layers cache-friendly: dependency manifests first, source last. _(when: dockerfile)_
- **DOCKER-004** — `COPY` only what's needed; rely on `.dockerignore` to keep context small. _(when: dockerfile)_
- **DOCKER-005** — Run as a non-root user in the final stage, with an explicit `USER <uid>:<gid>`; a user with no primary group runs with the root group. _(when: dockerfile)_
- **DOCKER-038** — Don't install or use `sudo` in runtime images; do root work before `USER` and drop privileges with `exec gosu` when a process must start as root. _(when: dockerfile)_
- **DOCKER-006** — Use `tini`/`dumb-init` (or run with `--init`) for proper PID 1 / signal handling. _(when: dockerfile)_
- **DOCKER-007** — Add `HEALTHCHECK` for long-lived services. _(when: dockerfile)_
- **DOCKER-009** — Use `RUN --mount=type=cache` for package managers under BuildKit; it must be optional for correctness, and a non-root step needs `uid=`/`gid=` on the mount. _(when: cache-mount)_
- **DOCKER-010** — Never bake secrets into layers; use `RUN --mount=type=secret`. _(when: dockerfile)_
- **DOCKER-011** — Minimize the final image: distroless / alpine / slim — choose with eyes open. _(when: dockerfile)_
- **DOCKER-012** — Set an absolute `WORKDIR` (leading `/`) explicitly; never rely on `/` or the base image's directory; `WORKDIR` does not expand a tilde. _(when: dockerfile)_
- **DOCKER-013** — Prefer `ENTRYPOINT` (exec form) + exec-form `CMD` over shell form; single quotes silently fall back to shell form, and a derived `ENTRYPOINT` resets an inherited `CMD`. _(when: dockerfile)_
- **DOCKER-014** — Use HereDoc syntax (`RUN <<EOF ... EOF`) for multi-line `RUN` blocks. _(when: dockerfile)_
- **DOCKER-015** — Use `set -o pipefail` (or exec-form bash) for piped `RUN` commands. _(when: dockerfile)_
- **DOCKER-016** — Prefer `COPY --link` unless the copy relies on earlier filesystem state (destination symlinks, an existing directory's mode); with `--link`, `--chown` must be numeric. _(when: dockerfile)_
- **DOCKER-017** — Scope BuildKit cache mount `id=` by `${TARGETARCH}` for multi-platform builds. _(when: cache-mount)_
- **DOCKER-036** — Redeclare global and platform `ARG`s (`ARG TARGETARCH`) inside each stage that uses them; otherwise they expand to an empty string with no error. _(when: dockerfile)_
- **DOCKER-037** — Use `ARG` or an inline `RUN` prefix for build-only values like `DEBIAN_FRONTEND`, not `ENV`, which persists at runtime and silently overrides `--build-arg`. _(when: dockerfile)_
- **DOCKER-018** — Remove the `docker-clean` snippet from the image's apt.conf.d before mounting an APT cache (otherwise the cache is silently wiped after every install). _(when: cache-mount)_
- **DOCKER-019** — `apt-get update` and `apt-get install` must share a single `RUN` — split layers cache the package index separately and serve stale data on rebuild. _(when: dockerfile)_
- **DOCKER-020** — Pass `--no-install-recommends` to `apt-get install` (and the RHEL `--setopt=install_weak_deps=False` equivalent) — recommends pull in tens of MB of unneeded packages. _(when: dockerfile)_
- **DOCKER-021** — `pip install` takes `--no-cache-dir` and uv takes `--no-cache` / `UV_NO_CACHE=1`, unless the install is wrapped in a BuildKit cache mount; the default cache bloats the layer. _(when: dockerfile)_
- **DOCKER-022** — Replace deprecated `MAINTAINER` (flagged by the `MaintainerDeprecated` check) with `LABEL org.opencontainers.image.authors=...` / `.vendor=...`. _(when: dockerfile)_
- **DOCKER-023** — Declare OCI image labels (`org.opencontainers.image.source`, `.revision`, `.version`, `.created`, `.licenses`) for traceability; declare per-build ARGs after the last `RUN` so they don't bust its cache. _(when: ci-build)_
- **DOCKER-024** — Avoid `chmod 777` / `chmod -R 777`; almost always masks a UID mismatch that wants `chown` instead. _(when: dockerfile)_
- **DOCKER-025** — `EXPOSE` must agree with the port `CMD`/`ENTRYPOINT` actually binds; drift breaks `docker run -P`, compose `expose:`, and reverse-proxy auto-discovery. _(when: dockerfile)_
- **DOCKER-026** — Never `curl ... | sh` without checksum verification — fetch remote artifacts with `ADD --checksum=sha256:...` (Dockerfile ≥1.6) or verify `sha256sum` before executing. _(when: dockerfile)_
- **DOCKER-027** — Pin `# syntax=docker/dockerfile:1` at the top of every Dockerfile; don't pin an older minor like `:1.8`, except pin a full version when the file sets `# check=error=true`. _(when: dockerfile)_
- **DOCKER-028** — Use `COPY --exclude=<pattern>` (Dockerfile ≥1.19) to filter unwanted files from multi-file copies instead of `COPY` + `RUN rm` or multi-COPY workarounds. _(when: dockerfile)_
- **DOCKER-029** — Run `docker build --check` as a Dockerfile lint step in CI (Buildx ≥0.15, Dockerfile ≥1.8); it exits non-zero on violations, `# check=error=true` (with a full-version syntax pin) fails ordinary builds too, and `skip=` names are case-sensitive. _(when: dockerfile)_
- **DOCKER-030** — Make image builds bit-for-bit reproducible via `SOURCE_DATE_EPOCH` + `--output type=image,...,rewrite-timestamp=true` (BuildKit ≥0.13); a changing epoch invalidates the cache from `WORKDIR` on. _(when: dockerfile)_
- **DOCKER-031** — Use `COPY --parents` (Dockerfile ≥1.20) to preserve source directory structure instead of flattening or post-copy `mkdir`. _(when: dockerfile)_
- **DOCKER-032** — Cap heavy `RUN` steps with build-time resource limits (`--resource cpu=,memory=`) on shared builders. _(when: dockerfile)_ _(requires buildkit>=0.31, dockerfile>=1.25)_
- **DOCKER-033** — Pin `RUN --network=none` on steps that must not touch the network, to enforce reproducibility. _(when: dockerfile)_
- **DOCKER-035** — Bind-mount build-only inputs (`RUN --mount=type=bind`, output written outside the read-only mount) instead of `COPY`ing them into a layer and the build cache. _(when: dockerfile)_

## Rules — Dev containers

See [`references/devcontainer.md`](./references/devcontainer.md).

- **DEVC-001** — Map host UID/GID to avoid file-ownership pain on bind mounts (`updateRemoteUserUID`; it skips taken UIDs, is off on macOS, only re-owns `$HOME`, and misfires under rootless Docker). _(when: devcontainer)_
- **DEVC-002** — Put long-running installs in the **image**, not `postCreateCommand`. _(when: devcontainer)_
- **DEVC-003** — Use official `features` for common tooling instead of hand-rolling; always write the major tag (`:1` pins the feature major; untagged means `:latest`, which can be a newer major), the `version` option is the tool version; avoid deprecated legacy, GitHub-release and renamed Feature IDs. _(when: devcontainer)_
- **DEVC-004** — Pick the right lifecycle hook: `onCreateCommand` vs `updateContentCommand` vs `postCreateCommand` vs `postStartCommand` vs `postAttachCommand`; every in-container hook sees the mounted source, prebuild hooks get no user secrets (credential steps go in `postCreateCommand`), and a failing hook skips all later ones. _(when: devcontainer)_
- **DEVC-028** — Pick the lifecycle command form deliberately: a string runs in `/bin/sh`, an array is argv with no shell (`&&` and `$VARS` pass literally), an object runs its entries in parallel and all must succeed; `runArgs` is argv too. _(when: devcontainer)_
- **DEVC-005** — Mount cache volumes for language package managers (uv, pnpm, go module cache, cargo, pip). _(when: devcontainer)_
- **DEVC-006** — Be deliberate about `mounts` and `workspaceFolder`: never mount key files or credential dirs (SSH goes through the agent, DEVC-019); set `workspaceMount` together with `workspaceFolder`, mount the repo root, and set `workspaceFolder` explicitly in Compose configs (it defaults to `/`). _(when: devcontainer)_
- **DEVC-007** — Choose `remoteUser` vs `containerUser` consciously; on images that supply a non-root user (mcr devcontainers images do it via their metadata label) set neither. _(when: devcontainer)_
- **DEVC-008** — Don't commit secrets in `devcontainer.json`; use `${localEnv:...}` or a mounted env file. `containerEnv`/`remoteEnv` are not secret handling (`docker inspect` shows `containerEnv`), so setup-only credentials go through `--secrets-file` / Codespaces secrets. _(when: devcontainer)_
- **DEVC-009** — Declare required `customizations.vscode.extensions` and settings the project assumes. _(when: devcontainer)_
- **DEVC-010** — Lifecycle scripts must be idempotent (they re-run on rebuild). _(when: devcontainer)_
- **DEVC-011** — Prefer `image` or `build` + a pinned base; avoid bare `Dockerfile` references that resolve ambiguously. _(when: devcontainer)_
- **DEVC-012** — Cross-platform host mount paths use `${localEnv:HOME}${localEnv:USERPROFILE}`; an empty or missing bind source is a hard mount error, and `${localEnv:VAR:default}` covers only an unset variable. _(when: devcontainer)_
- **DEVC-013** — Two-tier named volume naming: `<repo>-<tool>` for shared caches, `<repo>-<purpose>-${devcontainerId}` for per-worktree state (`.venv`, history, tool auth). _(when: devcontainer)_
- **DEVC-014** — On macOS, mount `.venv` (and other heavy tool-generated dirs) as a named volume — bind-mounted Python venvs are dramatically slower through VirtioFS. On Linux too when host and container both run uv: a shared venv symlinks an interpreter missing on the other side, so each side deletes and rebuilds it. _(when: devcontainer)_
- **DEVC-015** — Persist agentic CLI tool state (the home-directory `.claude`, `.codex`, `.config/gh` dirs, etc.) in per-worktree named volumes. Don't bind-mount these from the host — leaks tokens and conversation history both directions. Don't omit the mount — every rebuild wipes login state. _(when: devcontainer)_
- **DEVC-016** — Use `forwardPorts` + `portsAttributes` for editor port forwarding, but the devcontainer CLI ignores them — use `appPort` (published on `127.0.0.1`) for headless use, with the server listening on `0.0.0.0` inside the container (a loopback-bound server resets published connections); `runArgs` only for flags the spec doesn't model. _(when: devcontainer)_
- **DEVC-017** — Add capabilities deliberately via the first-class `capAdd` / `securityOpt` properties (they also reach compose, unlike `runArgs`); never default to `privileged`. The merge only adds privilege: a Feature's or image label's `privileged: true` wins over your `false`, so audit what you pull in. _(when: devcontainer)_
- **DEVC-018** — Set `"init": true` at the devcontainer.json level (it also reaches Compose configs; `services.<x>.init: true` is an alternative) so signals + zombie reaping work — not `runArgs --init`, which Compose configs silently ignore; same DOCKER-006 rationale, at the dev-container layer. _(when: devcontainer)_
- **DEVC-019** — SSH and git credentials: bind the host ssh-agent socket (the CLI never forwards it), never key files or the host SSH dir; pin known_hosts; strip credential helpers and host pagers from a copied gitconfig. _(when: devcontainer)_
- **DEVC-020** — Use the top-level `secrets` property to declare *recommended* secret names (Codespaces offers an optional prompt; the devcontainer CLI ignores it); `--secrets-file` feeds lifecycle commands only. _(when: devcontainer)_
- **DEVC-021** — Commit `devcontainer-lock.json` (stable, generated by default in CLI ≥0.87.0) for reproducible feature versions; use `--frozen-lockfile` in CI. _(when: devcontainer)_
- **DEVC-022** — Declare `hostRequirements.gpu` for GPU dev containers; don't hard-code `runArgs --gpus all` (the CLI adds it when it detects a GPU). _(when: devcontainer)_
- **DEVC-023** — `containerEnv` reaches every process (`docker exec`, agents); `remoteEnv` only tool-spawned ones; `${containerEnv:VAR}` is valid only in `remoteEnv`. _(when: devcontainer)_
- **DEVC-024** — Configs started headless (CLI, CI, agents) must do what VS Code does for you: agent forwarding, gitconfig, known_hosts, port forwarding, GPG. _(when: devcontainer)_
- **DEVC-025** — A Docker socket (docker-outside-of-docker) is root on the host — every credential boundary is moot with it, especially with auto-approve agents; make it an explicit, documented choice. _(when: devcontainer)_
- **DEVC-026** — Pin mcr dev container images to `<image-major>-<lang>-<os>` (e.g. `python:3-3.14-trixie`) or a digest; short tags float across image majors and OS releases, which breaks features. _(when: devcontainer)_
- **DEVC-027** — Set `"overrideCommand": false` when the image's `CMD` must run: image/Dockerfile configs default to `true` (CMD replaced by a sleep loop), Compose configs to `false`. _(when: devcontainer)_

## Rules — docker-compose

See [`references/compose.md`](./references/compose.md).

- **COMPOSE-001** — Use `depends_on` with `condition: service_healthy`, not bare `depends_on`; add `restart: true` (≥2.17) to restart on dependency updates and `required: false` (≥2.20) for optional dependencies. _(when: compose)_
- **COMPOSE-002** — Pick named volumes vs bind mounts deliberately; start relative bind sources with `./`, and use long syntax with `create_host_path: false` when a missing source must be an error rather than a new root-owned directory. _(when: compose)_
- **COMPOSE-003** — Use `env_file` for non-secret, per-environment config (credentials go to secrets, SEC-009); `environment:` beats `env_file` even when empty, later env files win, and optional files need `required: false`. _(when: compose)_
- **COMPOSE-004** — Gate optional services with `profiles` (tools, debug, monitoring); a dependency in an inactive profile is an error, not auto-enabled — share the profile, leave the dependency unprofiled, or use `required: false`. _(when: compose)_
- **COMPOSE-005** — Commit `compose.override.yml` as the shared dev overlay; prod uses `-f`, personal tweaks a gitignored `compose.local.yml`. _(when: compose)_
- **COMPOSE-035** — Override files append `ports`/`expose`/`dns`/`tmpfs` and merge volumes/secrets/configs by target; use `!override` / `!reset` to replace or clear a list, and check the merge with `docker compose config`. _(when: compose)_
- **COMPOSE-006** — Compose v2 ignores the top-level `version:` key — remove it from new files. _(when: compose)_
- **COMPOSE-033** — Choose the project name deliberately: a unique `-p`/`COMPOSE_PROJECT_NAME` per CI build on shared runners; a fixed top-level `name:` only when volumes must survive any checkout directory, since it makes every worktree share them. _(when: compose)_
- **COMPOSE-039** — An explicit `name:` on a top-level volume, network or config is used verbatim and shared across projects; set it only for deliberately shared resources (with `external: true` in consumers). _(when: compose)_
- **COMPOSE-007** — Define explicit `networks` for multi-service apps; don't rely on the default bridge for everything. _(when: compose)_
- **COMPOSE-036** — Address services as `<service>:<container port>` (db:5432, not the published host port), never by container IP; reach the host via `extra_hosts: host.docker.internal:host-gateway`. _(when: compose)_
- **COMPOSE-037** — Keep ordinary services off `network_mode: host` (host-wide network access, no service DNS, `ports:` silently discarded with a warning) and `network_mode: bridge` (no service-name resolution). _(when: compose)_
- **COMPOSE-041** — Publish only ports the host needs; an unqualified `ports:` mapping binds 0.0.0.0 and bypasses the host firewall — bind dev-only ports to `127.0.0.1:HOST:CONTAINER` and don't publish backing services at all. _(when: compose)_
- **COMPOSE-009** — Use `restart: unless-stopped` for long-lived services; it differs from `always` only in keeping a manually stopped container stopped across a daemon restart. _(when: compose)_
- **COMPOSE-010** — Use YAML anchors / `extends` instead of duplicating service definitions. _(when: compose)_
- **COMPOSE-011** — Healthchecks belong on the services that need to be waited on, not the waiters. _(when: compose)_
- **COMPOSE-012** — Run per-service setup (migrations, volume chown) as `pre_start` steps (Compose ≥5.3.0; skipped after success, rerun on definition change, failure or recreate); keep a `restart: "no"` one-shot gated by `service_completed_successfully` for setup several services share — it reruns on every `up`. Make both idempotent. _(when: compose)_
- **COMPOSE-013** — Postgres: mount the data volume at `/var/lib/postgresql/data` for ≤17 and at `/var/lib/postgresql` for 18+ (version-qualified `PGDATA`); the wrong level silently writes to an anonymous volume. _(when: compose)_
- **COMPOSE-014** — Reverse-proxy healthchecks hit a *local* endpoint (e.g. nginx `location = /__healthz`), not a path that proxies upstream — otherwise backend slowness restarts the proxy. _(when: compose)_
- **COMPOSE-015** — Use `develop.watch` (Compose ≥ 2.22) for hot-reload — `sync` / `rebuild` / `restart` / `sync+restart` / `sync+exec` per path, plus `initial_sync`; the image needs `stat`/`mkdir`/`rmdir` and a writable target (`COPY --chown`), `ignore` is relative to the rule's `path`, and `.venv/`/`node_modules/` stay unsynced. _(when: compose)_
- **COMPOSE-016** — Use the top-level `configs:` block for non-secret config files; pairs cleanly with `secrets:` (SEC-009) and avoids the "single-file bind mount becomes a directory" footgun. _(when: compose)_
- **COMPOSE-017** — Set `pull_policy` explicitly on shared / production stacks; the default `missing` silently runs stale images for mutable tags other than `latest` (which is always pulled). `daily` / `weekly` / `every_<duration>` sit in between. _(when: compose)_
- **COMPOSE-034** — When one service's Dockerfile builds `FROM` another service's image, declare `build.additional_contexts: {base: "service:<name>"}` — Compose builds in parallel and doesn't order builds by `image:` name. _(when: compose)_
- **COMPOSE-018** — Know the two unrelated `.env` mechanisms: project-dir `.env` (parse-time `${VAR}` substitution) vs `env_file:` (runtime container env). Shell variables win; `--env-file` replaces the project `.env` rather than layering over it; inspect with `docker compose config`. _(when: compose)_
- **COMPOSE-031** — Mark required interpolated variables `${VAR:?message}` and optional ones `${VAR:-default}`; a bare unset `${VAR}` becomes an empty string with only a warning (`postgres:${V}` → `postgres:`). _(when: compose)_
- **COMPOSE-032** — Escape literal `$` as `$$` in compose files (container-side vars in command/healthcheck, via explicit `sh -c`); in env files single-quote values with `$` or use `format: raw` — otherwise `ab$cd` arrives as `ab`. _(when: compose)_
- **COMPOSE-023** — Set `security_opt: ["no-new-privileges:true"]` and `cap_drop: [ALL]` (adding back only needed caps) on production services; `no-new-privileges`, `=true` and `:true` are equivalent spellings. _(when: compose)_
- **COMPOSE-026** — Declare `logging:` on long-lived services — prefer the `local` driver (rotates by default); on `json-file` set `max-size` + `max-file`, since it has no size limit and silently fills the host disk. _(when: compose)_
- **COMPOSE-038** — Set `deploy.resources.limits` (memory, cpus, pids) on long-lived services on shared hosts — plain Compose applies them; one source per limit; rootless needs cgroup v2 + systemd. _(when: compose)_
- **COMPOSE-040** — Put container labels (Traefik, autoheal, discovery) under the service's `labels:`; `deploy.labels` never reach containers under plain Compose. _(when: compose)_
- **COMPOSE-019** — Use the `include:` directive (Compose ≥2.20) to compose modular sub-applications into a parent project; distinct from `extends:` (single-service) and `-f` (file-level merge). A redeclared included service silently merges — customize via a per-include override path. Remote `oci://` sources need Compose ≥2.34 (and COMPOSE-028). _(when: compose)_
- **COMPOSE-020** — Use the `gpus:` shorthand (Compose ≥2.30) for GPU services; on shared hosts set `count` or `device_ids` (never both — unset reserves every GPU), and give the longhand `capabilities`. _(when: compose)_
- **COMPOSE-021** — Use the top-level `models:` block (Compose ≥2.38) for declarative AI-model dependencies via Docker Model Runner (Docker Engine or Desktop); `<KEY>_URL` / `<KEY>_MODEL` injected as env vars. _(when: compose)_
- **COMPOSE-027** — Use `post_start` / `pre_stop` lifecycle hooks (Compose ≥2.30) for privileged (`user: root` / `privileged`) setup/teardown without weakening the service; `post_start` has no ordering guarantee vs the entrypoint, so pre-start work belongs in `pre_start` (COMPOSE-012). _(when: compose)_
- **COMPOSE-028** — Treat remote compose sources (`include: oci://`, `extends`, `-f oci://`) as code: pin by `@sha256:` digest, review the fully resolved `docker compose config`, audit the transitive chain, host on a registry you control — and require Compose ≥2.40.2 (or v5) for CVE-2025-62725. _(when: compose)_ _(requires compose>=2.40.2)_
- **COMPOSE-029** — Set `init: true` on services whose image runs the app as PID 1 without an init — signals get forwarded and zombies reaped; doesn't replace DOCKER-006 for images you build. _(when: compose)_
- **COMPOSE-042** — Raise `stop_grace_period` on databases, queue consumers and workers that flush on SIGTERM; Compose SIGKILLs after 10 s by default. _(when: compose)_
- **COMPOSE-030** — Gate CI on `docker compose config --quiet` over the deploy's exact `-f` files and env — catches schema typos, undefined services and unset `${VAR:?}`, not bad values or host state. _(when: compose)_

## Rules — Buildx & cache backends

See [`references/buildx.md`](./references/buildx.md). Pairs with the
BuildKit-side rules under "Dockerfile authoring" (DOCKER-009, 010, 017)
and "Security & build" (SEC-002, 004, 006).

- **BUILDX-001** — Pick a cache backend per scenario: `gha` for GitHub Actions, `registry` for portable CI, `inline` for simplest-but-limited, `local` for single-machine. A `type=local` dir that persists between runs needs `--cache-to ...,reset=true` (Buildx ≥0.35) or it grows on every export. _(when: cache-export)_
- **BUILDX-002** — Cache reuse requires **both** `--cache-from` and `--cache-to`. Specify `--cache-from` multiple times (branch + main fallback). Use `mode=max` for multi-stage builds. Give every cache export its own location: a registry cache `ref` distinct from the pushed image, one per branch, and a `type=gha` `scope=` per image. `image-manifest=true` is the default since BuildKit v0.21. _(when: cache-export)_
- **BUILDX-003** — Choose `--load` (single-arch, into local daemon), `--push` (registry, multi-arch OK), or `--output type=...` (OCI archive, local dir). Without one of these, multi-arch builds run and **discard** the result. _(when: ci-build)_
- **BUILDX-004** — Use `docker buildx bake` for multi-target / declarative builds — replaces long CLI commands, reads `compose.yaml` directly, builds all targets in parallel. _(when: dockerfile)_
- **BUILDX-005** — The default `docker` driver exports caches and builds multi-platform images only with the containerd image store, and never exports tarballs. Switch to `docker-container` (or `kubernetes`) for full BuildKit features. `setup-buildx-action` does this for you in CI. _(when: ci-build)_
- **BUILDX-006** — Avoid QEMU emulation for non-trivial multi-arch builds. For compiled languages, cross-compile first: put the build stage on `FROM --platform=$BUILDPLATFORM` and pass `TARGETOS`/`TARGETARCH` to the compiler. Use native nodes per architecture (a multi-node builder, or separate CI jobs + `imagetools create`) for builds that can't cross-compile. _(when: multi-platform)_
- **BUILDX-007** — Use `docker buildx debug build` (still experimental) — or `docker buildx dap build` (out of experimental since buildx v0.33.0) for editor integration — for interactive step-through of failing builds; replaces the `RUN sleep 999` + `docker exec` hack. _(requires buildx>=0.12 (preview))_ _(when: dockerfile)_ _(requires buildx>=0.12 (preview))_
- **BUILDX-008** — The buildx CLI attaches min-mode provenance by default, which already makes the push an index. `build-push-action` uses `mode=max` (it records build-arg values) in public repos. A registry that can't store an index needs `--provenance=false` / `BUILDX_NO_DEFAULT_ATTESTATIONS=1`, not `mode=min`. One that rejects OCI-artifact attestations (BuildKit ≥0.32) needs `oci-artifact=false`. On the classic image store, attestations fail with the `docker` driver and on `--load`. SBOMs are opt-in, and they scan only the final stage unless a stage declares `ARG BUILDKIT_SBOM_SCAN_STAGE=true`. _(when: attestations)_
- **BUILDX-009** — Use `bake` matrix targets + composable HCL attributes for multi-variant builds. _(when: dockerfile)_
- **BUILDX-010** — Pin the Docker GitHub Actions (`setup-buildx-action@v4`, `build-push-action@v7`, `bake-action@v7`) by commit SHA. The SHA does not pin the toolchain, so also pin Buildx (`version:`) and BuildKit (`driver-opts: image=moby/buildkit:<tag>`) when the build depends on a minimum feature version. _(when: ci-build)_
- **BUILDX-011** — Gate build inputs (digest-pinned images, approved sources) with a `Dockerfile.rego` build policy; in CI load it with `--policy reset=true,filename=Dockerfile.rego` so a missing policy fails (`strict=true` didn't, live). _(requires buildx>=0.31 (preview), buildkit>=0.27)_ _(when: dockerfile)_ _(requires buildx>=0.31 (preview), buildkit>=0.27)_
- **BUILDX-012** — In workflows with read-only Actions cache access (`issue_comment`, `pull_request_target`, `pull_request` `types: [closed]`), keep `cache-from: type=gha`, omit `cache-to`, and fill the cache from a default-branch `push` workflow. Don't mask `failed to reserve cache` with `ignore-error=true`. _(when: ci-build)_
- **BUILDX-013** — `docker/build-push-action` builds from the Git context of the triggering ref by default and ignores files that earlier steps generated. Set `context: .` after checkout when the build needs them. _(when: ci-build)_
- **BUILDX-014** — On `pull_request`, build but don't log in or push: gate `docker/login-action` with `if: github.event_name != 'pull_request'` and set `push: ${{ github.event_name != 'pull_request' }}`. _(when: ci-build)_
- **BUILDX-015** — Copy or promote multi-platform images between registries with `docker buildx imagetools create --tag <dst> <src>` (whole index, all platforms + attestations), not `docker pull` + `tag` + `push`, which carries only the host platform. _(when: multi-platform)_

## Rules — Security & build

See [`references/security-build.md`](./references/security-build.md).

- **SEC-001** — Always have a `.dockerignore`. At minimum: `.git`, `node_modules`, `__pycache__`, `.venv`, `.env*`, `dist/`, build artifacts. _(when: dockerfile)_
- **SEC-002** — Use BuildKit (the default builder since Docker Engine 23.0, or `docker buildx`). Many modern features depend on it. _(when: dockerfile)_
- **SEC-004** — Build multi-platform with `buildx` only when needed; single-platform is cheaper. _(when: dockerfile)_
- **SEC-005** — Never leak `.git`, lockfile-only artifacts, or `node_modules` into images. _(when: dockerfile)_
- **SEC-006** — Use BuildKit secret mounts for build-time credentials (`env=` exposes one as a variable, Dockerfile ≥1.10; `required=true` fails the step when the secret is missing instead of running with it empty; file mounts are `0400` root-owned, so set `uid=` after a non-root `USER`; compose grants a build secret only under `build.secrets`); never `ARG` them — build args persist in image history and provenance. _(when: build-secrets)_
- **SEC-008** — Combine related `RUN` steps (install + cleanup in one layer), not unrelated ones; layer count itself isn't the goal. _(when: dockerfile)_
- **SEC-009** — Use Compose's `secrets:` block (mounted as files under `/run/secrets/`) instead of `environment:` for any sensitive value — env vars leak via `docker inspect`, `/proc/<pid>/environ`, and logs. `file:` secrets are world-readable `0444` bind mounts; `uid`/`gid`/`mode` are ignored for them. _(when: compose)_
- **SEC-010** — Image references with `@sha256:` digest must be fully literal; don't templatize the digest in Jinja/copier (template drift makes the version+digest pair inconsistent) and don't split version + digest across separate variables. A template's version choices are each a complete literal `image:tag@sha256` string kept current by Renovate.
- **SEC-011** — Add `.venv`, `node_modules`, `target/`, `.gradle/`, tool caches and other platform-specific build dirs to `.dockerignore` — they're at best slow, at worst architecture-incompatible inside the image. _(when: uv)_
- **SEC-012** — Never `COPY .env` / `COPY *.env` into images; it picks up `.env` only when `.dockerignore` misses it, and then bakes secrets into a layer permanently. _(when: dockerfile)_
- **SEC-013** — `.git/` must be in `.dockerignore` and never `COPY`'d (or `ADD --keep-git-dir=true`'d) into the final image — leaks full repo history, rotated secrets, internal codenames. _(when: dockerfile)_
- **SEC-014** — Flag `ARG`/`ENV` names matching `*SECRET*` / `*TOKEN*` / `*PASSWORD*` / `*KEY*` / `*CREDENTIAL*` — values get baked into image metadata visible via `docker history` / `docker inspect`. _(when: dockerfile)_
- **SEC-028** — Don't declare the predefined proxy `ARG`s (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, ...) in a Dockerfile — `--build-arg` alone works and stays out of `docker history` and the cache key; declaring one writes the proxy URL (often with credentials) into history. _(when: dockerfile)_
- **SEC-015** — `.dockerignore` must be *comprehensive*, not just present; check coverage against a baseline (VCS, secrets, per-ecosystem build dirs, tool caches, editor/OS, Docker meta), and audit any `<name>.Dockerfile.dockerignore` too — it replaces the root file. _(when: dockerfile)_
- **SEC-016** — Broad `COPY . .` is only safe when `.dockerignore` passes SEC-015; without comprehensive ignores, prefer narrow per-subtree copies. _(when: dockerfile)_
- **SEC-017** — Prefer `COPY` over `ADD`; flag only un-checksummed `ADD <url>` (silent supply chain) and implicit local tar auto-extract. `ADD --checksum=` is the recommended remote fetch; pin a remote Git build context with `?tag=…&checksum=<sha>`, and authenticate downloads with `HTTP_AUTH_TOKEN_<host>` secrets, never a token in the URL. _(when: dockerfile)_
- **SEC-019** — `.env` files must be in `.gitignore` (not only `.dockerignore`) *and* must not already be git-tracked — `git rm --cached` is required to actually untrack a previously-committed `.env`.
- **SEC-020** — Use `RUN --mount=type=ssh` (or `ADD git@...`) + `docker buildx build --ssh default` for SSH-authenticated git/dep access during builds, or a host-scoped `GIT_AUTH_TOKEN.<host>` secret for HTTPS (`GIT_AUTH_HEADER.<host>` for hosts that don't take `x-access-token` Basic auth); never `COPY id_rsa` or `ARG SSH_PRIVATE_KEY`. _(when: build-secrets)_
- **SEC-029** — Don't grant builds privileged entitlements — flag `RUN --security=insecure` (equivalent to `--privileged`), `RUN --network=host`, `--allow`/`--allow-insecure-entitlement`, and compose `build.entitlements` / `build.privileged`. _(when: dockerfile)_
- **SEC-021** — Pin third-party scanner/tool images by digest and CI Actions by commit SHA — floating tags get hijacked (Trivy supply-chain compromise, CVE-2026-33634). _(when: ci-build)_
- **SEC-022** — Sign images with keyless cosign and verify with explicit `--certificate-identity` + `--certificate-oidc-issuer` (Docker Content Trust was removed in Engine 29; its Notary v1 service shuts down 2026-12-08); verify third-party bases against the publisher's identity before adopting a new digest pin. _(when: ci-build)_
- **SEC-023** — Prefer a hardened/minimal verified base (Docker Hardened Images — Apache-2.0, distroless runtime variants — Chainguard, distroless) for production runtimes. _(when: dockerfile)_
- **SEC-024** — Run the daemon rootless (or with userns-remap, enabled on a fresh install — it hides existing objects and blocks `--privileged` / host namespaces without `--userns=host`) on hosts that run untrusted workloads; neither replaces DOCKER-005. _(when: docker-host)_
- **SEC-030** — Don't strip default confinement from containers: no `privileged: true`, `seccomp=unconfined`, `apparmor=unconfined` or `label=disable` on compose services or `docker run` (dev containers: DEVC-017).
- **SEC-027** — Scan the built image in CI and fail on severity (`trivy image --exit-code 1 --severity CRITICAL,HIGH --ignore-unfixed <digest>`); Trivy exits 0 on findings by default. _(when: ci-build)_

## Rules — Python + uv

See [`references/uv-python.md`](./references/uv-python.md). Apply alongside
the general Dockerfile rules above (especially DOCKER-001, 002, 003, 009,
and SEC-010, SEC-011).

- **UV-001** — Install `uv` via `COPY --from=ghcr.io/astral-sh/uv:VERSION@sha256:DIGEST /uv /uvx /bin/`. Pin the literal version+digest pair (SEC-010) and verify it with `gh attestation verify`; the uv image is distroless, so the copy carries no extra weight. _(when: uv)_
- **UV-002** — Two-pass sync: bind-mount manifests + `uv sync --locked --no-install-project` first; then copy source + `uv sync --locked`. Dependency layer caches independently from source edits. Declare `ARG TARGETARCH` in the stage before using it in a cache `id=`. _(when: uv)_
- **UV-003** — Set `ENV UV_LINK_MODE=copy` whenever a BuildKit cache mount is used — silences the cross-filesystem hard-link warning that fires on every install otherwise. _(when: uv)_
- **UV-004** — Set `ENV UV_COMPILE_BYTECODE=1` (or pass `--compile-bytecode`) for production images; trades a bit of build time for noticeably faster cold starts. _(when: uv)_
- **UV-005** — `--locked` asserts the lockfile is up to date with `pyproject.toml`; `--frozen` skips that check. Default to `--locked` everywhere; use `--frozen` only in workspace pass-1 where members aren't yet present. _(when: uv)_
- **UV-006** — For minimal final images, use the copy-from-builder pattern: install with `--no-editable` in a builder stage, then `COPY --from=builder /app/.venv /app/.venv` into a clean final stage — source doesn't ship. Single stage: mount uv per `RUN` (`--mount=from=ghcr.io/astral-sh/uv:…,source=/uv,target=/bin/uv`) so the binary never ships. _(when: uv)_
- **UV-007** — Set `UV_PYTHON_DOWNLOADS=0` (use the base image's Python, don't download another) and optionally `UV_PROJECT_ENVIRONMENT` pointed at the system prefix (install into system Python, skip the `.venv` indirection) for system-Python builds. _(when: uv)_
- **UV-008** — Workspace pattern: pass 1 uses `uv sync --frozen --no-install-workspace` (members not yet copied), pass 2 uses `uv sync --locked` after the source is in place. _(when: uv)_
- **UV-009** — Point `UV_TOOL_BIN_DIR` at the system bin dir when installing CLI tools via `uv tool install` on bases other than uv's derived images (those already set it), so the binaries land on `PATH` instead of uv's default executable dir (`$HOME/.local/bin`). _(when: uv)_
- **UV-010** — Use `ENV UV_NO_DEV=1` and the `UV_NO_INSTALL_*` env vars instead of repeating flags across the two-pass sync. _(when: uv)_
- **UV-011** — Migrate off the removed `bookworm` uv base tags to `trixie` (uv 0.10.0 dropped `bookworm`/`bookworm-slim`). _(when: uv)_
- **UV-012** — When bind-mounting a uv project for development (`-v .:/app`, compose `- .:/app`), add an anonymous volume `/app/.venv` after it so the image-built venv isn't hidden by the host's; after a rebuild run `docker compose up -V`. Prefer `develop.watch` with `ignore: .venv/` (COMPOSE-015); dev containers use DEVC-014. _(when: uv)_

## Reference file structure

Every rule in every `references/` file follows the same shape:

- **What** — the rule, restated precisely.
- **Why** — a concrete failure mode if you violate it (real footgun, not theory).
- **How** — a minimal correct snippet.
- **When NOT to apply** — exceptions and tradeoffs.

When citing a rule in a response or PR, give the rule ID and a one-line
summary; expand only if the user asks for the rationale.
