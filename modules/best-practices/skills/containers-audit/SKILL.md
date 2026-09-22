---
name: containers-audit
description: Audit Dockerfile, compose and devcontainer.json files against the containers-best-practices rule set and offer each fix interactively. Walks every container file under a path, prints a prioritized findings report keyed by rule ID (DOCKER-, COMPOSE-, DEVC-, BUILDX-, SEC-, UV-), then applies fixes one at a time with per-finding approval. Use when asked to audit, scan, lint or harden containers, Dockerfiles, compose files or dev containers; never autofixes.
user-invocable: true
argument-hint: "[path]"
tags: [containers, docker, audit]
---

# Containers audit

Walk every container-related file under the target path against the
`containers-best-practices` skill's rule set, present a prioritized findings
list, and offer each fix interactively. Audit target: $ARGUMENTS — when none is
given, the current directory.

This skill is read-mostly: read files and search the tree freely, edit a file
only after explicit per-finding approval, and never delete or move files or
run `docker` commands during the audit. If the target path is outside the
current repository, refuse and ask the user to change into it first — that
keeps the blast radius bounded.

## Step 1 — Discover

Search the target path for container files:

- `**/Dockerfile`
- `**/*.dockerfile`
- `**/.devcontainer/devcontainer.json`
- `**/.devcontainer/**/devcontainer.json`
- `**/devcontainer.json`
- `**/compose.yml`, `**/compose.yaml`
- `**/docker-compose.yml`, `**/docker-compose.yaml`
- `**/compose.override.yml`, `**/compose.override.yaml`
- `**/docker-compose.override.yml`, `**/docker-compose.override.yaml`

Also check for:

- `.dockerignore` at the repo root and next to each Dockerfile — both *existence* (SEC-001) and *coverage* (SEC-015, against the baseline in the rule).
- `.gitignore` at the repo root — needed for SEC-019.
- Any `.env`, `.env.*` (excluding `.env.example` / `.env.template`) at the repo root — flag for SEC-012, SEC-019.
- `.git/` directory presence — confirms `.dockerignore` needs SEC-013 coverage.

Print a short summary of what was found, grouped by type. If nothing was found, exit cleanly with a one-line message — do not proceed.

## Step 2 — Load the rule set

Read the `containers-best-practices` skill so its rule index is in context —
it ships in this same module at `../containers-best-practices/SKILL.md`. Then
read the relevant reference file for each *type* of file you discovered:

- Any Dockerfile → `../containers-best-practices/references/dockerfile.md`
- Any `devcontainer.json` → `../containers-best-practices/references/devcontainer.md`
- Any compose file → `../containers-best-practices/references/compose.md`
- Always → `../containers-best-practices/references/security-build.md` (covers `.dockerignore`, BuildKit, scanning)

Also load:

- `../containers-best-practices/references/uv-python.md` whenever the repo shows Python+uv signals: `pyproject.toml` with `[tool.uv]`, `uv.lock` present, `COPY --from=ghcr.io/astral-sh/uv` in the Dockerfile, or any `uv sync` invocation. The uv rules cross-cut the Dockerfile and security categories.
- `../containers-best-practices/references/buildx.md` when the repo has a `docker-bake.hcl`, a CI config using `docker/build-push-action` or `docker buildx`, or a `Dockerfile` with `RUN --mount=type=cache` (cache backend choice becomes relevant).

Read only the rules relevant to what you found — don't load all files if only a Dockerfile is present.

## Step 3 — Analyze each file

For every discovered file, walk it line-by-line against the relevant rules. Record each violation as a finding:

```
{
  severity: "high" | "medium" | "low",
  rule_id:  "DOCKER-005",
  file:     "path/to/Dockerfile",
  line:     42,            // best-effort; omit if not applicable
  problem:  "Runs as root in final stage",
  fix:      "Add a non-root USER directive after the final COPY step"
}
```

### Severity mapping

| Severity | Examples |
|----------|----------|
| **high** | Runs as root (DOCKER-005); no `.dockerignore` (SEC-001); `.dockerignore` exists but fails baseline coverage check (SEC-015); `.venv` / `node_modules` not in `.dockerignore` (SEC-011); explicit `COPY .env` / `COPY .env.*` (SEC-012); `.git/` not in `.dockerignore` or explicitly `COPY .git` (SEC-013); secret-shaped `ARG`/`ENV` names — `*SECRET*`, `*TOKEN*`, `*PASSWORD*`, `*KEY*`, `*CREDENTIAL*` (SEC-014); `COPY . .` without comprehensive `.dockerignore` (SEC-016); `.env` present in repo but not in `.gitignore`, or `.env` is git-tracked (SEC-019); secrets in layers (DOCKER-010 / SEC-006); env-var secrets instead of compose `secrets:` block (SEC-009); missing signal handler in long-lived entrypoint (DOCKER-006); bare `depends_on` without healthcheck (COMPOSE-001); secrets in `devcontainer.json` (DEVC-008); host SSH directory or a private key file bind-mounted into a dev container (DEVC-019); APT cache mount with `docker-clean` hook still in place (DOCKER-018 — silently broken cache); piped `RUN` without `pipefail` for an installer download (DOCKER-015); `curl ... \| sh` or a downloaded artifact executed without checksum verification (DOCKER-026); SSH key `COPY`'d or passed as `ARG` instead of `RUN --mount=type=ssh` (SEC-020); third-party scanner/tool image or CI Action on a floating tag instead of a digest / commit SHA (SEC-021, BUILDX-010); `cosign verify` without `--certificate-identity` + `--certificate-oidc-issuer` (SEC-022); `include:` / `-f` with an `oci://` source on Compose older than 2.40.2 (COMPOSE-028); a host credential directory — SSH, cloud credentials, registry config — bind-mounted into a dev container beyond the SSH case DEVC-019 already covers (DEVC-006); agentic CLI tool state (`.claude`, `.codex`, etc.) bind-mounted from the host instead of a per-worktree named volume (DEVC-015); `privileged: true` (or `--privileged`) used instead of a specific capability (DEVC-017); `COPY` pulling in more than needed, relying on an absent or thin `.dockerignore` (DOCKER-004); legacy (non-BuildKit) builder in use (SEC-002); `.git`, lockfile-only artifacts, or `node_modules` leaked into the image (SEC-005); `uv` installed via package manager / curl script instead of pinned `COPY --from=ghcr.io/astral-sh/uv` (UV-001) |
| **medium** | Base image not pinned (DOCKER-002 / SEC-010); inefficient cache ordering (DOCKER-003); `apt-get update` and `install` in separate `RUN`s (DOCKER-019); `apt-get install` without `--no-install-recommends` (DOCKER-020); deprecated `MAINTAINER` directive (DOCKER-022); `chmod 777` / `chmod -R 777` (DOCKER-024); `EXPOSE` doesn't match the port `CMD`/`ENTRYPOINT` binds (DOCKER-025); `ADD <url>` without `--checksum=` or `ADD foo.tar.gz` with surprising auto-extract (SEC-017); missing `security_opt: ["no-new-privileges:true"]` on production services (COMPOSE-023); missing `logging:` block with `max-size` + `max-file` on long-lived services (COMPOSE-026); single-pass `uv sync` (no UV-002 split); missing `HEALTHCHECK` (DOCKER-007); heavy installs in `postCreateCommand` (DEVC-002); `${containerEnv:...}` used inside `containerEnv` (DEVC-023); `runArgs --gpus all` hard-coded next to `hostRequirements.gpu` (DEVC-022); dev container base image on a floating short tag, or `docker-outside-of-docker` with `moby` left at its default on a Debian trixie base (DEVC-026); `version:` key still present in Compose v2 file (COMPOSE-006); migrations as a long-lived service instead of `service_completed_successfully` init (COMPOSE-012); proxy healthcheck probes an upstream path (COMPOSE-014); `UV_LINK_MODE` unset with cache mounts (UV-003); `UV_COMPILE_BYTECODE` unset on a production image (UV-004); single-platform `${TARGETARCH}` missing from cache `id=` in a multi-platform build (DOCKER-017), or used in a stage that never declares `ARG TARGETARCH` (UV-002 / UV-008); no `# syntax=docker/dockerfile:1` line (DOCKER-027); no `docker build --check` gate in CI, or one that cannot fail (DOCKER-029); mutable tag without an explicit `pull_policy` on a shared stack (COMPOSE-017); long-lived service whose image has no init and no `init: true` (COMPOSE-029); `--frozen` where `--locked` belongs (UV-005); workspace pass 1 without `--frozen --no-install-workspace` (UV-008); removed `bookworm` uv tags (UV-011); cache written with `--cache-to` but never read with `--cache-from` (BUILDX-002); multi-arch `buildx build` with no `--push`/`--output`, or `--load` of a multi-platform build (BUILDX-003); multi-arch or full-cache-export build on the default `docker` driver without the containerd image store (BUILDX-005); attestations pushed to a registry that cannot store an index (BUILDX-008); inline `environment:` used for a secrets-adjacent value instead of `env_file` (COMPOSE-003); no explicit `networks:` segmentation for a multi-service app (COMPOSE-007); healthcheck placed on the depending service instead of the depended-on one (COMPOSE-011); no UID/GID mapping, leaving root-owned files on bind-mounted output (DEVC-001); work placed in the wrong lifecycle hook (DEVC-004); `remoteUser`/`containerUser` set without checking the base image's own default (DEVC-007); a lifecycle script that isn't idempotent (DEVC-010); floating dev container base/feature version instead of pinned (DEVC-011); named volume missing the `<repo>-` / `${devcontainerId}` scoping (DEVC-013); no `devcontainer-lock.json` committed, or CI not using `--frozen-lockfile` (DEVC-021); single-stage build carrying build-only dependencies into the runtime image (DOCKER-001); final image not minimized (no distroless/alpine/slim consideration) (DOCKER-011) |
| **low** | Missing `WORKDIR` (DOCKER-012); unnecessary shell-form `CMD` (DOCKER-013); `pip install` without `--no-cache-dir` and no cache mount (DOCKER-021); missing OCI image labels — `org.opencontainers.image.source` / `.revision` / `.version` (DOCKER-023); missing VS Code extensions in devcontainer (DEVC-009); dev container used headless (CLI / agents) but relying on editor-only behavior — `forwardPorts`, agent forwarding, gitconfig copy (DEVC-024); excessive `RUN` chaining or no use of YAML anchors (COMPOSE-010); multi-line `RUN` could use HereDoc syntax (DOCKER-014); mount-path uses `${localEnv:HOME}` instead of cross-platform form (DEVC-012); Postgres volume mounted at the wrong path for its major version (COMPOSE-013); `COPY` + `RUN rm` instead of `COPY --exclude` (DOCKER-028); flattening `COPY` instead of `COPY --parents` (DOCKER-031); no `SOURCE_DATE_EPOCH` / `rewrite-timestamp` on a released image (DOCKER-030); heavy `RUN` on a shared builder without `--resource` limits (DOCKER-032); network-free step without `RUN --network=none` (DOCKER-033); bare bind mount of the workspace for hot-reload instead of `develop.watch` (COMPOSE-015); single-file bind mount instead of `configs:` (COMPOSE-016); `.env` vs `env_file:` confusion (COMPOSE-018); `-f` chains instead of `include:` (COMPOSE-019); `deploy.resources.reservations.devices` instead of `gpus:` (COMPOSE-020); hand-wired local inference service instead of `models:` (COMPOSE-021); privileged service for one-off setup that `post_start`/`pre_stop` could do (COMPOSE-027); no cache backend in CI (BUILDX-001); long `buildx build` command lines instead of bake (BUILDX-004); QEMU emulation for CPU-heavy multi-arch builds (BUILDX-006); `RUN ... \|\| sleep` debugging hack left in a Dockerfile (BUILDX-007); per-variant build commands instead of a bake matrix (BUILDX-009); dependencies copied without the `--no-editable` builder/final split (UV-006); system-Python build without `UV_PYTHON_DOWNLOADS=0` (UV-007); `uv tool install` without `UV_TOOL_BIN_DIR` on `PATH` (UV-009); flags repeated instead of `UV_NO_DEV` / `UV_NO_INSTALL_*` (UV-010); bind-mounting a stateful directory (e.g. DB data) instead of a named volume (COMPOSE-002); no `profiles` gating for optional/heavyweight services (COMPOSE-004); local overrides piled into the base compose file instead of `compose.override.yml` (COMPOSE-005); long-lived service missing `restart: unless-stopped` (COMPOSE-009); hand-rolled tool install instead of an official devcontainer Feature (DEVC-003); no cache volume for a language package manager, so every rebuild re-downloads (DEVC-005); bind-mounted `.venv` (or other heavy generated dir) instead of a named volume (DEVC-014); `forwardPorts`/`portsAttributes` relied on for a config also run headless, instead of `appPort` (DEVC-016); no `init: true` in a dev container whose image has no init process (DEVC-018); recommended secrets undeclared in the top-level `secrets` property (DEVC-020); package-manager install with no `RUN --mount=type=cache` (DOCKER-009); `COPY` that could use `--link` but doesn't (DOCKER-016); multi-platform buildx build for a single-arch deployment target (SEC-004); unrelated steps chained into one `RUN`, or a cache-busting mix of concerns (SEC-008) |

If a rule's applicability is genuinely ambiguous (e.g. you can't tell whether
the entrypoint is long-lived), record it as **needs-judgment** instead of
fabricating a severity — list it separately at the end. A Docker socket mounted into a dev container (DEVC-025) is always needs-judgment: ask whether host-root access from inside the container is an accepted, documented risk. So are a production runtime on a full general-purpose base (SEC-023) and a host running untrusted workloads without rootless mode or userns-remap (SEC-024) — neither is decidable from the file alone.

## Step 4 — Present findings

Print a single consolidated report:

```
Found N findings across M files:

  high:   X
  medium: Y
  low:    Z
  needs-judgment: W

By file:
  path/Dockerfile (3 findings)
    [high]   DOCKER-005 — line 18 — Runs as root in final stage
    [med]    DOCKER-002 — line 1  — Base image pinned by tag, not digest
    [low]    DOCKER-012 — line 1  — No WORKDIR set
  .devcontainer/devcontainer.json (1 finding)
    [med]    DEVC-002 — postCreateCommand runs apt install (move to image)
```

## Step 5 — Interactive fix loop

Walk the findings in severity order (high → medium → low). For each one, ask
the user — with the harness's structured question tool when it has one,
otherwise a numbered prompt (`Reply with 1=apply, 2=skip, 3=diff, 4=skip-file,
5=stop`) answered on the next turn:

- **Apply this fix** — perform the edit and confirm what changed.
- **Skip this finding** — leave it; move on.
- **Show me the diff first** — print the proposed old and new text, then ask again.
- **Skip rest of this file** — move to the next file's findings.
- **Stop auditing** — abort the loop and jump to the summary.

**Never apply a fix without explicit per-finding approval.** This skill never autofixes.

For each fix:

1. Re-read the file (state may have changed since the initial scan).
2. Construct the minimal edit to address the rule. If the fix is non-trivial (e.g. restructuring into multi-stage), describe the change in words and ask the user to confirm before editing.
3. After editing, briefly state what was applied and which rule ID it resolved.

## Step 6 — Summary

When done, print:

```
Audit complete.

Applied:  A fixes
Skipped:  S findings
Deferred: D findings (needs-judgment — manual review recommended)

Next steps:
  - <one-line nudge per remaining high-severity finding>
  - Consider running the containers audit again after manual changes.
```

If `.dockerignore` was missing and the user approved creating it, list the
patterns that were added so they can review.
