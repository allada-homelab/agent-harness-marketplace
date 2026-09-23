# Dev container rules

Detailed explanation for each `DEVC-NNN` rule.

Citations point at [the Dev Containers spec](https://containers.dev/implementors/spec/)
and [the devcontainer.json reference](https://containers.dev/implementors/json_reference/).
When uncertain about a property name or default, verify there before claiming
specifics — the spec has evolved.

---

## DEVC-001 — Map host UID/GID to avoid file-ownership pain on bind mounts

**What.** On Linux hosts, the container's user should have the same UID/GID
as the host user, otherwise files created in the bind-mounted workspace
appear as owned by a different UID — and edits from the host (or container)
fail with permission errors.

**Why.** A workspace bind-mounted into a container where the container user
is `root` (UID 0) ends up with files owned by root on the host after every
`pip install`, `npm install`, or generated artifact. The next host-side
`git status` or editor save fails. macOS/Windows hide this via the file
sharing layer, but Linux dev container users hit it constantly.

**How.** Host matching is done by **`updateRemoteUserUID`** (default
`true`): on Linux, when `remoteUser` or `containerUser` is set (directly or
through the image's `devcontainer.metadata` label), the tool rewrites that
user's UID/GID to the host user's before the container starts. The
official `mcr.microsoft.com/devcontainers/*` images ship a non-root user
for this — **set (or inherit) `remoteUser` and let the remap run**.

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3-3.14-trixie",
  "remoteUser": "vscode"
  // updateRemoteUserUID defaults to true — no feature needed on this image
}
```

Know its three limits (devcontainers CLI source):

1. **Skipped when the host UID is already taken** by another user in the
   image — the build logs `User with UID exists (<name>=<uid>).` and leaves
   the remote user unchanged.
2. **Off on macOS** — the CLI only runs it on Linux hosts.
3. **Only `$HOME` is re-owned** (`chown -R` of the user's home folder).
   Anything the image baked elsewhere as UID 1000 — a venv under `/opt`,
   a `/data` dir, a tool cache — stays owned by 1000 and breaks with
   `EACCES` when the host UID differs. Re-own those paths in
   `onCreateCommand`:

```jsonc
"onCreateCommand": "sudo chown -R \"$(id -u):$(id -g)\" /opt/venv /data"
```

For custom base images that don't already have a non-root user, use the
official `common-utils` feature (option keys are **`userUid` /
`userGid`**, not `uid` / `gid`) and let `updateRemoteUserUID` do the host
matching:

```jsonc
{
  "build": { "dockerfile": "Dockerfile" },
  "remoteUser": "vscode",
  "features": {
    "ghcr.io/devcontainers/features/common-utils:2": {
      "username": "vscode",
      "userUid": "automatic",
      "userGid": "automatic"
    }
  }
}
```

`"automatic"` does **not** mean "detect the host UID": for a new user it
omits `--uid`/`--gid` so `useradd` picks the next free ID, and for an
existing user it keeps the current ID. If the user already exists,
`common-utils` does not error — it `usermod`s/`groupmod`s it to any
explicit `userUid`/`userGid` you pass.

Don't pass the host UID as a build arg via `${localEnv:UID}`: `UID` is a
shell variable in bash/zsh, not an exported environment variable, so the
tool sees it as empty. If you must bake the UID (e.g. `updateRemoteUserUID`
is skipped because the UID is taken), have `initializeCommand` write
`id -u` into a file the build reads, or free the conflicting UID in the
Dockerfile.

Cite: [json_reference — updateRemoteUserUID](https://containers.dev/implementors/json_reference/#general-properties),
[CLI updateUID.Dockerfile L20, L31 (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/scripts/updateUID.Dockerfile#L20-L31),
[CLI containerFeatures.ts L425 — Linux-only gate](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/containerFeatures.ts#L425),
[common-utils main.sh — existing user / automatic](https://github.com/devcontainers/features/blob/47406487f9b4965e4f9865f20b86805b1e2d5c0f/src/common-utils/main.sh#L447-L470).

**When NOT to apply.** macOS/Windows-only dev — the host file-sharing layer
abstracts UID mapping for you (and the CLI skips the remap there anyway).
Still worth doing for portability across contributors.

---

## DEVC-002 — Put long-running installs in the image, not `postCreateCommand`

**What.** Anything that takes more than a few seconds (`apt install`, language
toolchains, large CLI tools) belongs in the Dockerfile or as a `feature`,
not in `postCreateCommand` / `onCreateCommand`.

**Why.** Lifecycle commands run *every time the dev container is created*
(not just first-time setup). Heavy installs there:

- Make every "rebuild dev container" cycle take minutes.
- Are not cached by Docker — each rebuild repeats them from scratch.
- Defeat the whole point of a pre-built image.

A teammate cloning the repo waits 15 minutes the first time, then another
15 every time they rebuild — instead of pulling a ready image in seconds.

**How.**

```dockerfile
# in the dev container Dockerfile — cached, fast on rebuild
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev jq \
 && rm -rf /var/lib/apt/lists/*
```

```jsonc
// in devcontainer.json — only fast, repo-state-dependent things
"postCreateCommand": "uv sync"
```

Reserve `postCreateCommand` for:

- Installing project dependencies (`uv sync`, `npm ci`, `bundle install`) — fast and depends on the lockfile in the repo.
- Wiring up git hooks (`pre-commit install`).
- Generating a `.env` from a template if one doesn't exist.

**When NOT to apply.** When the install genuinely depends on per-clone state
(e.g. a private credential mounted at create time). Even then, prefer
caching aggressively.

---

## DEVC-003 — Use official `features` for common tooling

**What.** Use [`ghcr.io/devcontainers/features/*`](https://containers.dev/features)
for common tooling (git, docker-outside-of-docker, node, python, terraform,
aws-cli, etc.) instead of hand-rolling install commands in the Dockerfile.

**Why.** Features are versioned, tested across base images, support arm64
and amd64, and integrate cleanly with the dev container lifecycle. Some
also skip the install if the requested version is already present (e.g.
the `python` feature).

**How.**

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu-22.04",
  "features": {
    "ghcr.io/devcontainers/features/docker-outside-of-docker:1": {},
    "ghcr.io/devcontainers/features/python:1": { "version": "3.12" },
    "ghcr.io/devcontainers/features/terraform:1": { "version": "1.7" }
  }
}
```

Pin both: the `:1` in the feature reference pins the *feature's* major
version, and the `"version"` option is the *tool/language* version the
feature installs (the `python` feature's default is `os-provided`).
`devcontainer-lock.json` (DEVC-021) pins the exact feature digest.

Cite: [python feature options](https://github.com/devcontainers/features/blob/47406487f9b4965e4f9865f20b86805b1e2d5c0f/src/python/devcontainer-feature.json#L4-L21),
[skip-if-present in python install.sh](https://github.com/devcontainers/features/blob/47406487f9b4965e4f9865f20b86805b1e2d5c0f/src/python/install.sh#L488-L492).

**When NOT to apply.** Tooling not covered by an existing feature, or when
you need an unusual configuration that a feature doesn't expose. Then bake
it into a custom Dockerfile (DEVC-002).

---

## DEVC-004 — Pick the right lifecycle hook

**What.** Use the right hook for the right kind of work. The dev container
spec defines (in order of execution within a single create/start cycle):

| Hook | Runs | Where | Use for |
|---|---|---|---|
| `initializeCommand` | Every time the tool starts/resumes the dev container (not just first create) | Host | Fetch credentials, generate compose `.env`, decrypt local secrets |
| `onCreateCommand` | Once per container *create* (re-runs on "Rebuild Container") | Container | Heavy one-time setup that depends on container state but not repo state (rare — usually goes in image) |
| `updateContentCommand` | After `onCreateCommand` during create. Locally that is once per create; only cloud services / prebuilds re-run it to refresh a cached container | Container | Idempotent steps a prebuild should refresh when repo content changes (uncommon) |
| `postCreateCommand` | Once per create, after content is in place | Container | Install repo deps from lockfile, wire git hooks |
| `postStartCommand` | Inside container, every start (including restart and resume) | Container | Refresh transient state, start dev services |
| `postAttachCommand` | When the editor attaches | Container | Print welcome message, open a default file |

A separate top-level **`waitFor`** field controls which hook the editor
*blocks on* before attaching (default `updateContentCommand`). If you put
critical setup in `postCreateCommand`, set `"waitFor": "postCreateCommand"`
so the editor doesn't attach to a half-set-up container. Otherwise, in
VS Code, `postCreateCommand` runs in the background and a fast typer can
hit a "command not found" error before `uv sync` finishes.

That background behavior is editor-side. The devcontainer CLI's `up`
runs every hook synchronously, in order, and returns only after
`postAttachCommand`. There `waitFor` matters only with
`--skip-non-blocking-commands`, where it marks the hook to stop after.
Under the CLI, `onCreateCommand`, `updateContentCommand` and
`postCreateCommand` run once per container create (`updateContentCommand`
re-runs only with `--prebuild`), `postStartCommand` on every start, and
`postAttachCommand` on every `up`.

Cite: [containers.dev — Lifecycle scripts](https://containers.dev/implementors/json_reference/#lifecycle-scripts),
[CLI injectHeadless.ts — hook order and markers (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-common/injectHeadless.ts#L367-L446).

**Why.** Mixing these up causes subtle bugs: heavy work in `postStartCommand`
slows every editor restart; repo-dependent work in `onCreateCommand` runs
too early (content may not be mounted yet, depending on configuration);
host-side work in any `post*` hook never runs at all.

**How.** Typical pattern:

```jsonc
{
  "initializeCommand": "cp -n .env.example .env || true",
  "postCreateCommand": "uv sync && pre-commit install",
  "postStartCommand": "echo 'Ready. Run: uv run dev'",
  "waitFor": "postCreateCommand"
}
```

**When NOT to apply.** When you only need one of these (most projects need
`postCreateCommand` and nothing else — that's fine). Even then, setting
`waitFor: postCreateCommand` is cheap insurance.

---

## DEVC-005 — Mount cache volumes for package managers

**What.** Mount named volumes at the package manager's cache location so
that cache state persists across container rebuilds.

**Why.** Without this, every "rebuild dev container" wipes the package
manager cache and the next `uv sync` / `npm ci` / `cargo build` re-downloads
the world. Named volumes are independent of the container's filesystem and
survive rebuilds.

**How.**

```jsonc
{
  "mounts": [
    "source=devcontainer-uv-cache,target=/home/vscode/.cache/uv,type=volume",
    "source=devcontainer-pnpm-store,target=/home/vscode/.local/share/pnpm/store,type=volume",
    "source=devcontainer-go-mod,target=/go/pkg/mod,type=volume",
    "source=devcontainer-cargo,target=/usr/local/cargo/registry,type=volume"
  ]
}
```

For npm: `~/.npm`. For pip: `~/.cache/pip`. For Maven: `~/.m2`. For Gradle:
`~/.gradle/caches`.

**When NOT to apply.** Single-developer repos where rebuild frequency is
low and re-downloading is cheap. Repos in air-gapped environments where the
cache is already a vendored on-disk mirror.

---

## DEVC-006 — Be deliberate about `mounts` and `workspaceFolder`

**What.** Know the difference between:

- `workspaceMount` + `workspaceFolder` — where the repo lives inside the container.
- `mounts` — extra volumes/bind-mounts beyond the workspace.

Don't blindly mount `~/.ssh` or `~/.aws` or `~/.docker` from the host without
thinking through what's exposed.

**Why.** A bind mount of `~/.ssh` exposes every key the host user has — to
any process running in the container, including ones triggered by malicious
dev dependencies. Same for `~/.aws/credentials` (AWS keys), `~/.docker/config.json`
(registry tokens), `~/.netrc` (npm/git credentials).

**How.** Mount only what's needed, read-only when possible, and never
private key files:

```jsonc
"mounts": [
  // ssh: the host's agent socket, never ~/.ssh or a key file — see DEVC-019
  "source=${localEnv:SSH_AUTH_SOCK:/dev/null},target=/ssh-agent.sock,type=bind",

  // a single non-secret config file, read-only
  "source=${localEnv:HOME}${localEnv:USERPROFILE}/.config/myapp/config.toml,target=/home/vscode/.config/myapp/config.toml,type=bind,readonly"
]
```

For SSH, use the agent (DEVC-019): VS Code forwards it automatically when
a host agent is running; the devcontainer CLI does not, so bind the
socket yourself. There is no official "ssh-keys" feature — the official
features list has only `sshd` (an SSH *server*). The Docker socket is not
a credential mount you can scope: it is root on the host (DEVC-025).

**When NOT to apply.** Trusted, isolated dev container with no external
dependencies — but assume otherwise unless you've audited.

---

## DEVC-007 — Choose `remoteUser` vs `containerUser` consciously

**What.** Two related but distinct settings:

- `containerUser` — the user the container's *processes* run as. Equivalent to Dockerfile `USER`. **Defaults to the image's final `USER` directive.** For `mcr.microsoft.com/devcontainers/*` images that is `root`.
- `remoteUser` — the user the editor's *remote server* (`vscode-server`) and lifecycle commands run as. **Defaults to `containerUser`** when unset. The `mcr.microsoft.com/devcontainers/*` images set `remoteUser` (`vscode` for python, `node` for javascript-node) in their `devcontainer.metadata` image label, which the tooling merges in. That label, not the image `USER`, is why you land as `vscode`.

**Why.** The framing isn't "if you don't set these, you get root" — it's
"these override the image's defaults, and a wrong override is worse than
no override." When the base image already supplies a sensible non-root
user — via its final `USER` or a `remoteUser` in its `devcontainer.metadata`
label — the safest action is to set **neither** and let defaults flow
through. Setting `containerUser` overrides the image's `USER`, which can
break feature-installed users that expected the original UID.

A common mistake is forcing `containerUser: vscode` on an mcr
devcontainers image: the image's `USER` is `root` by design (features and
entrypoints run as root), and the label already makes `vscode` the
remote user. Forcing it runs the container's entrypoint and features'
entrypoint scripts as `vscode`, which can break the ones that need root.

A separate setting, **`userEnvProbe`** (default `loginInteractiveShell`),
controls how the editor probes the user's shell environment. On slow
shells (heavy `.bashrc`/`.zshrc` setups) this is often the culprit for
slow editor attach — set it to `loginShell` or `interactiveShell` if you
notice startup delays.

Cite: [containers.dev — remoteUser, containerUser, userEnvProbe](https://containers.dev/implementors/json_reference/),
[devcontainers/images python — remoteUser via metadata](https://github.com/devcontainers/images/blob/c04ecb19a95e23cf7a4275993cdb3119e9f97c60/src/python/.devcontainer/devcontainer.json#L28-L29)
(image config `User` is `root`: `docker buildx imagetools inspect mcr.microsoft.com/devcontainers/python:3-3.14-trixie`).

**How.**

```jsonc
// custom image without a pre-configured non-root user — set both explicitly
{
  "build": { "dockerfile": "Dockerfile" },
  "remoteUser": "vscode",
  "containerUser": "vscode"
}
```

```jsonc
// official devcontainer image — let the image's defaults flow through
{
  "image": "mcr.microsoft.com/devcontainers/python:3-3.14-trixie"
  // neither set; image USER is root, remoteUser "vscode" comes from the image's metadata label
}
```

If editor attach is slow, add:

```jsonc
"userEnvProbe": "loginShell"   // skip the interactive shell probe
```

**When NOT to apply.** Containers that genuinely need to run privileged
processes (rare in dev workflows — and if needed, scope it to specific
processes, not the editor). Setting `containerUser` when the image
already has the correct USER — usually unnecessary, sometimes harmful.

---

## DEVC-008 — Don't commit secrets in `devcontainer.json`

**What.** `devcontainer.json` is checked into the repo. Anything inside it
— including `containerEnv` values, `args`, `mounts` — is visible to anyone
with read access. Secrets must be sourced from outside the file.

**Why.** Real failure mode: `containerEnv.API_KEY = "sk-..."` committed to
GitHub. Public/private doesn't matter — collaborators, CI logs, and search
indexers all see it. GitHub's secret scanner will flag it, but only after
it's already on someone's screen.

**How.** Use `${localEnv:VAR_NAME}` to pull from the host environment at
container-create time:

```jsonc
{
  "containerEnv": {
    "GITHUB_TOKEN": "${localEnv:GITHUB_TOKEN}",
    "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}"
  }
}
```

Or mount a host file:

```jsonc
"mounts": [
  "source=${localEnv:HOME}/.config/myapp/credentials,target=/home/vscode/.config/myapp/credentials,type=bind,readonly"
]
```

Document required host env vars in the repo README so contributors know what
to set before opening the dev container.

**When NOT to apply.** Never — secrets always belong outside the file.

---

## DEVC-009 — Declare required VS Code extensions and settings

**What.** Include `customizations.vscode.extensions` and `settings` for
anything the project assumes (linters, language servers, formatters,
project-specific settings like `python.defaultInterpreterPath`).

**Why.** A teammate opens the dev container and the Python language server
isn't installed, ruff isn't running, and they get confused why CI fails on
formatting their PR. Declaring extensions ensures the *editor* state
matches the *container* state.

**How.**

```jsonc
{
  "customizations": {
    "vscode": {
      "extensions": [
        "charliermarsh.ruff",
        "ms-python.python",
        "ms-python.vscode-pylance",
        "tamasfe.even-better-toml"
      ],
      "settings": {
        "python.defaultInterpreterPath": "/app/.venv/bin/python",
        "[python]": {
          "editor.defaultFormatter": "charliermarsh.ruff",
          "editor.formatOnSave": true
        }
      }
    }
  }
}
```

Pin extension versions only if you've hit a specific issue; usually
unpinned is fine since extensions are user-installed each time.

**When NOT to apply.** Editor-agnostic dev containers (used via JetBrains
Gateway, plain SSH). Then the extensions block is harmless but unused.

---

## DEVC-010 — Lifecycle scripts must be idempotent

**What.** Every `*Command` hook may run more than once (especially
`postStartCommand`). Scripts must produce the same result whether run once
or fifty times.

**Why.** A `postCreateCommand` of `cp .env.template .env` overwrites edits
on every rebuild. A `postStartCommand` of `pre-commit install` is fine
(idempotent). A `postCreateCommand` that appends to `~/.bashrc` will
accumulate duplicates.

**How.**

```bash
# good — idempotent
cp -n .env.example .env || true          # -n: don't overwrite existing
git config --global init.defaultBranch main
pre-commit install --install-hooks

# bad — destroys user edits
cp .env.example .env
```

Test by running the lifecycle command twice in a row — output should
converge to a stable state.

**When NOT to apply.** Genuinely first-time-only operations belong in
`onCreateCommand`, which runs once. But idempotency is still a good
defensive habit.

---

## DEVC-011 — Prefer `image` or `build` + pinned base; avoid ambiguous Dockerfile references

**What.** Be explicit about how the container image is sourced:

- `"image": "mcr.microsoft.com/devcontainers/python:3-3.12-trixie"` — use a pre-built image, pinned per DEVC-026.
- `"build": { "dockerfile": "Dockerfile" }` — build a custom image.
- `"dockerComposeFile": "../docker-compose.yml"` — use compose.

Pick one and pin the base.

**Why.** Mixing modes or leaving versions unpinned causes drift between
contributors. `mcr.microsoft.com/devcontainers/python:latest` will be a
different Python next month — and your `uv` lockfile won't tell you why
imports started failing.

**How.**

```jsonc
{
  "name": "myapp-dev",
  "build": {
    "dockerfile": "Dockerfile",
    "args": { "PYTHON_VERSION": "3.12" }
  }
}
```

With the Dockerfile pinning its base:

```dockerfile
ARG PYTHON_VERSION=3.12
FROM mcr.microsoft.com/devcontainers/python:${PYTHON_VERSION}@sha256:...
```

**When NOT to apply.** When sharing a compose stack with production is the
right call (`dockerComposeFile` mode) — then the base pinning lives in
the compose file's image references.

---

## DEVC-012 — Cross-platform mount paths use `${localEnv:HOME}${localEnv:USERPROFILE}`

**What.** When you need to bind-mount a path from the host home directory
(SSH keys, AWS credentials, dotfiles), construct the source path by
concatenating both `HOME` and `USERPROFILE` env vars. Normally one is
set per OS, so the concatenation produces a valid path on each platform
(see the Git Bash caveat below).

**Why.** Linux/macOS use `HOME`; Windows uses `USERPROFILE`. An unset
`${localEnv:VAR}` substitutes as the empty string, so plain
`${localEnv:HOME}` on Windows turns `source=${localEnv:HOME}/.aws` into
`source=/.aws` — a nonexistent path, and the container fails to start
(`bind source path does not exist`). A variable that makes the *whole*
source empty (`source=${localEnv:SSH_AUTH_SOCK}` with the var unset) is a
hard `docker run` error: `invalid value for 'source': value is empty`.
Either way the container never comes up. Plain `${localEnv:USERPROFILE}`
has the symmetric problem on Linux/macOS.

For a variable that may be unset, give a default with
`${localEnv:VAR:default}`. The default applies only when the variable is
**unset**; a variable set to the empty string still substitutes as empty
(devcontainers CLI `variableSubstitution.ts`). So a fail-loud check in
`initializeCommand` is still worth having for set-but-empty values.

**How.**

```jsonc
{
  "mounts": [
    // good — works on Linux, macOS, AND Windows
    "source=${localEnv:HOME}${localEnv:USERPROFILE}/.ssh/known_hosts,target=/home/vscode/.ssh/known_hosts,type=bind,readonly",
    "source=${localEnv:HOME}${localEnv:USERPROFILE}/.aws,target=/home/vscode/.aws,type=bind,readonly"
  ]
}
```

```jsonc
// bad — HOME unset on Windows ⇒ source=/.ssh/known_hosts ⇒ container fails to start
"source=${localEnv:HOME}/.ssh/known_hosts,target=/home/vscode/.ssh/known_hosts,type=bind,readonly"
```

```jsonc
// may-be-unset variable: default to a harmless path instead of an empty source
"source=${localEnv:SSH_AUTH_SOCK:/dev/null},target=/ssh-agent.sock,type=bind"
```

A bind source must exist, so create it on the host in `initializeCommand`
(e.g. `touch` the file) when it may be missing.

This pattern appears verbatim in the
[spec's json_reference example](https://containers.dev/implementors/json_reference/#variables-in-devcontainerjson)
(under "Variables in devcontainer.json"), so it's documented — but it's
a **workaround**, not a clean primitive. Cite for the default syntax:
[json_reference — `${localEnv:VARIABLE_NAME:default_value}`](https://containers.dev/implementors/json_reference/#variables-in-devcontainerjson),
[CLI variableSubstitution.ts L142-L154 (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-common/variableSubstitution.ts#L142-L154). Spec issue
[devcontainers/spec#335](https://github.com/devcontainers/spec/issues/335)
tracks adding a proper `${localEnv:HOME_OR_USERPROFILE}` variable.

**Important caveat — Git Bash / MSYS / Cygwin on Windows.** Under these
shells, **both** `HOME` *and* `USERPROFILE` are set:

```
HOME=/c/Users/jdoe          # MSYS-style path
USERPROFILE=C:\Users\jdoe   # Native Windows path
```

The concatenation becomes `/c/Users/jdoeC:\Users\jdoe` — an invalid
path, so the mount fails. If your
team uses Git Bash on Windows, prefer an explicit branching strategy in
host-side setup scripts, or wait for the spec primitive to land.

Same trick applies to `runArgs` and any other field that takes a host
path.

**When NOT to apply.** When your team is single-OS and you know the file
will never be opened on the other family. The concatenation is harmless
in that case — keep it as future-proofing. Also: when contributors use
Git Bash / MSYS — see caveat above.

---

## DEVC-013 — Two-tier named volume naming: shared caches vs per-worktree state

**What.** When you maintain multiple worktrees / branches of the same
repo, split your named volumes into two tiers:

- **Shared caches** — named with a fixed `<repo>-<tool>` prefix so every worktree of the repo reuses the same cache (uv cache, pnpm store, Cargo registry, pre-commit hooks).
- **Per-worktree state** — named with `<repo>-<purpose>-${devcontainerId}` so each worktree has its own isolated copy (`.venv`, tool authentication, shell history).

**Why.** Docker volume names are global per daemon. Without a `<repo>-`
prefix, your `uv-cache` volume collides with every other project on the
same machine. Without `${devcontainerId}` for per-worktree state,
rebuilding the dev container in one worktree can clobber another's
`.venv` (and `uv sync` writes absolute paths into console-script shebangs
that point at the *current* workspace path, so venvs are *not* shareable
across worktrees regardless).

**How.**

```jsonc
{
  "mounts": [
    // shared across all worktrees of this repo — cache reuse
    "source=myrepo-uv-cache,target=/home/vscode/.cache/uv,type=volume",
    "source=myrepo-pnpm-store,target=/home/vscode/.local/share/pnpm/store,type=volume",
    "source=myrepo-pre-commit,target=/home/vscode/.cache/pre-commit,type=volume",

    // per-worktree — isolated, won't contaminate siblings
    "source=myrepo-venv-${devcontainerId},target=/workspaces/${localWorkspaceFolderBasename}/.venv,type=volume",
    "source=myrepo-bash-history-${devcontainerId},target=/commandhistory,type=volume"
  ]
}
```

Pair with an `onCreateCommand` that `chown`s the mount targets to the
non-root container user. A new, empty named volume takes the content
*and ownership* of the target directory if it already exists in the
image. If the target path does not exist in the image (a `.venv` under
the workspace, `/commandhistory`), Docker creates the mountpoint
root-owned. See DEVC-007 / DEVC-010, and
[Docker — populate a volume using a container](https://docs.docker.com/engine/storage/volumes/#populate-a-volume-using-a-container).

**When NOT to apply.** Single-worktree workflows where you only ever
develop on one branch at a time. Even there, the `<repo>-` prefix is
worth keeping so volumes don't collide with other projects.

---

## DEVC-014 — Mount `.venv` (and other heavy build dirs) as a named volume on macOS, and on Linux when host and container both run uv

**What.** On macOS, Docker Desktop's file-sharing layer (VirtioFS / osxfs
/ gRPC-FUSE) adds substantial latency to every `stat`, `open`, and `read`
on bind-mounted paths. For Python projects this hits hardest at the
virtual environment — thousands of small files that get stat-ed on every
import, every `pytest` collection, every `uv sync`. Mount the `.venv` as
a *named volume* (per-worktree, see DEVC-013) so it lives entirely
inside the Linux VM instead of being proxied through the file-sharing
layer.

**Why.** Real numbers from real codebases: `pytest --collect-only` on a
medium Python project goes from 15 seconds (bind-mounted `.venv`) to
<1 second (named-volume `.venv`) on Apple Silicon Docker Desktop. The
same difference applies to `import` resolution, language server indexing,
and `uv sync`. The host editor doesn't need to see `.venv` files anyway —
they're tool-generated.

**How.**

```jsonc
{
  "name": "myproject-dev",
  "remoteUser": "vscode",
  "workspaceFolder": "/workspaces/myproject",
  "mounts": [
    // the .venv lives in the Linux VM, not osxfs — fast imports, fast pytest
    "source=myproject-venv-${devcontainerId},target=/workspaces/myproject/.venv,type=volume"
  ],
  "postCreateCommand": "uv sync"
}
```

Apply the same pattern to other large generated directories:
`node_modules/`, `target/` (Rust), `.gradle/caches/`, `dist/`, `build/`.

Two caveats:

1. **Ownership.** A named volume whose target doesn't exist in the image
   (the usual case for a workspace `.venv`) mounts root-owned. A target
   that exists in the image is copied into the empty volume, content and
   ownership included. Add an `onCreateCommand` to chown the root-owned
   ones to the non-root user (DEVC-010 covers the broader idempotency
   need).
2. **Per-worktree.** uv (and most tools) write absolute paths into venv
   metadata, so the venv is bound to the workspace path it was created
   for. Use `${devcontainerId}` to keep one volume per worktree.

**Linux hosts need the volume too when both sides run uv.** There is no
file-sharing overhead on Linux, but a bind-mounted `.venv` is shared
between host and container, and its `bin/python` symlinks (and
`pyvenv.cfg` `home`) the interpreter of whichever side created it — a
path that does not exist on the other side. `uv sync` then reports
"Removed virtual environment" and rebuilds it, so host and container
delete each other's venv on every alternation. A per-worktree named
volume gives the container its own `.venv`.

It does touch the host, though. To mount a volume at `.venv` inside the
bind-mounted workspace, the daemon creates the mountpoint in the host
checkout if it is missing. With a rootful daemon that directory is empty
and root-owned, so a later host `uv venv` or `uv sync` fails with
"Permission denied". Pre-create every such mountpoint as your user from
`initializeCommand`, which runs on the host before the container starts:

```jsonc
{
  "initializeCommand": "mkdir -p .venv"
}
```

**When NOT to apply.** Linux hosts where only the container ever runs uv
against the workspace (no file-sharing overhead, and no second side to
fight over the venv). Throwaway containers where the cold-sync cost of
recreating the venv each time is acceptable.

---

## DEVC-015 — Persist agentic CLI tool state in named volumes, not bind mounts

**What.** Modern coding-agent and CLI-tool state (`~/.claude` for Claude
Code, `~/.codex` for Codex CLI, `~/.config/gh` for GitHub CLI, `~/.aider`,
`~/.cursor-server`, etc.) should live in **per-worktree named volumes**
inside the dev container — not bind-mounted from the host, and not lost
on every rebuild.

**Why.** Three things go wrong with the obvious approaches:

1. **Bind-mount from host (`source=${localEnv:HOME}/.claude,target=/home/vscode/.claude,type=bind`).**
   Leaks every session transcript, conversation, and auth token between
   host and container. Tokens granted on the host now exist inside any
   container. Tokens granted in the container leak to the host. And
   Claude Code's `~/.claude/projects/` directory contains every prompt
   and response — sometimes hundreds of MB — that you probably don't
   want shared across environments.
2. **No mount at all.** Every dev container rebuild loses login state,
   conversation history, and configuration. You log back in, lose
   in-flight work, repeat.
3. **Bind-mount the workspace + let the agent put state in `./.cache/`.**
   The state ends up in your git working tree, accidentally committed,
   or excluded via `.gitignore` but still consuming workspace disk.

The right pattern: **per-tool named volumes, per-worktree** (combine
with the DEVC-013 two-tier naming). State persists across rebuilds,
stays isolated from the host, and survives `git worktree` work without
leaking between branches.

**How.**

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3-3.12-trixie",
  "remoteUser": "vscode",
  "mounts": [
    // Agentic CLIs — per-worktree named volumes
    "source=myrepo-claude-${devcontainerId},target=/home/vscode/.claude,type=volume",
    "source=myrepo-codex-${devcontainerId},target=/home/vscode/.codex,type=volume",
    "source=myrepo-aider-${devcontainerId},target=/home/vscode/.aider,type=volume",

    // GitHub CLI — auth token + config
    "source=myrepo-gh-${devcontainerId},target=/home/vscode/.config/gh,type=volume",

    // Shell history — useful but private
    "source=myrepo-commandhistory-${devcontainerId},target=/commandhistory,type=volume"
  ],

  // Targets that don't exist in the image mount root-owned; chown to the non-root user on create
  "onCreateCommand": "sudo mkdir -p /home/vscode/.claude /home/vscode/.codex /home/vscode/.aider /home/vscode/.config/gh /commandhistory && sudo chown -R vscode:vscode /home/vscode/.claude /home/vscode/.codex /home/vscode/.aider /home/vscode/.config /commandhistory"
}
```

For Bash history specifically, append a snippet to the user's profile
that points `HISTFILE` at the volume mount:

```jsonc
"postCreateCommand": "echo 'export HISTFILE=/commandhistory/.bash_history' >> ~/.bashrc"
```

**Decision tree for each piece of CLI tool state:**

| What | Where it should live | Why |
|---|---|---|
| Auth tokens (Claude, Codex, gh) | Per-worktree named volume | Don't leak host ↔ container; don't lose on rebuild |
| Conversation / session transcripts | Per-worktree named volume | Per-worktree isolation; don't mix work across branches |
| Shell history | Per-worktree named volume | Private to dev container; survives rebuilds |
| Tool config files (`~/.claude/settings.json`) | Per-worktree named volume *or* committed to repo as `.claude/` | If team-wide, commit it; if personal, volume |
| Project-specific state (`./.claude/`, `./.cursor/`) | Repo (gitignored if personal) | Stays with the project |
| Repo-level CLAUDE.md, AGENTS.md | **Committed to repo** | Shared knowledge for everyone |

**When NOT to apply.** Single-shot ephemeral containers where state
should explicitly *not* persist (CI builds, throwaway test runs).
Single-developer single-worktree setups where you don't need the
isolation — in that case, named volumes without `${devcontainerId}`
work fine.

---

## DEVC-016 — `runArgs` + port forwarding patterns

**What.** Three related but distinct knobs for what gets exposed and how
the container runs:

| Field | Purpose |
|---|---|
| `appPort` | Editor-agnostic: *published* with Docker `-p` when the container is created, so it works under any tool, including the devcontainer CLI. A number `P` is published as `-p 127.0.0.1:P:P` (loopback only); a string is passed to `-p` verbatim. |
| `forwardPorts` | List of container ports the *editor* forwards to the local machine. VS Code makes them clickable in the Ports panel. |
| `portsAttributes` | Per-port metadata for editor forwards: label, `onAutoForward` ("notify" / "openBrowser" / "silent"), protocol. |
| `runArgs` | Raw `docker run` flags appended at container start (image / Dockerfile configs only — not applied to Docker Compose). Use for things the spec doesn't model directly (ulimits, devices, sysctls). |

**Why.** `forwardPorts` + `portsAttributes` is the spec-recommended,
editor-aware way to expose ports — VS Code shows them in the "Ports"
panel, forwards them on `localhost`, and remembers them across
sessions. But it is implemented by the editor: the devcontainer CLI parses
`forwardPorts`/`portsAttributes` and never acts on them. A config that is
also started headless (`devcontainer up`, CI, coding agents) gets no
ports from `forwardPorts`. `appPort` is the working option there. The
spec's own advice to prefer `forwardPorts` assumes an editor is attached.
`runArgs` is the escape hatch for everything else. Capabilities, security
options, privileged mode and init have first-class properties
(DEVC-017, DEVC-018) — use those instead.

**How.**

```jsonc
{
  "image": "myimage",
  // editor sessions
  "forwardPorts": [3000, 5432, 8080],
  "portsAttributes": {
    "3000": { "label": "frontend", "onAutoForward": "openBrowser" },
    "5432": { "label": "postgres", "onAutoForward": "silent" },
    "8080": { "label": "api", "onAutoForward": "notify" }
  },
  "runArgs": [
    "--ulimit", "nofile=65536:65536"       // raise fd limit for high-concurrency tooling
  ]
}
```

```jsonc
{
  "image": "myimage",
  // started by the devcontainer CLI: published on host loopback as 127.0.0.1:3000
  "appPort": [3000]
}
```

Cite: [containers.dev — forwardPorts, portsAttributes, appPort](https://containers.dev/implementors/json_reference/#general-properties),
[runArgs is image/Dockerfile-specific](https://containers.dev/implementors/json_reference/#image-or-dockerfile-specific-properties),
[CLI singleContainer.ts L346-L348 — appPort publishing (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/singleContainer.ts#L346-L348),
[CLI imageMetadata.ts — forwardPorts only merged, never used (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/imageMetadata.ts#L192-L209).

**When NOT to apply.** When the container doesn't expose any services
(`forwardPorts` unnecessary). When the defaults are fine for `runArgs`
— don't sprinkle flags you don't need. `appPort` is unnecessary for a
config only ever opened in an editor.

---

## DEVC-017 — Use `securityOpt` / `capAdd` deliberately, not by reflex

**What.** Linux capabilities, AppArmor/SELinux profiles, and seccomp
profiles control what privileged operations the container can perform.
The spec has first-class, cross-orchestrator properties for them —
`capAdd`, `securityOpt`, `privileged` (and `init`, DEVC-018). Prefer
these over the equivalent `runArgs` flags: `runArgs` applies only to
image/Dockerfile configs, while these properties also reach Docker
Compose configs (the CLI writes them into its generated compose
override), and they merge with values from features and image metadata.

**Why.** A common mistake is `--privileged` (or `"privileged": true`)
when the actual need is one or two specific capabilities. `--privileged`
drops *all* security restrictions, including AppArmor/SELinux profiles,
seccomp filters, and capability bounds — turning the container into a
full host equivalent. Almost no dev workflow actually needs this.

Specific capabilities to know about for dev containers:

- `SYS_PTRACE` — native debuggers (gdb, lldb, strace, dtrace) need this to attach to processes.
- `NET_ADMIN` / `NET_RAW` — VPNs, packet captures, low-level networking.
- `SYS_ADMIN` — Docker-in-Docker without privileged; mount/unmount inside the container. Most dangerous; avoid unless required.

Seccomp/AppArmor:

- `seccomp=unconfined` — disable seccomp filter. Sometimes needed for native debugging on older kernels (`SYS_PTRACE` blocked by default seccomp profile).
- `apparmor=unconfined` — disable AppArmor. Sometimes needed for the same reason.

**How.**

```jsonc
{
  // good — add only what you need, as first-class properties
  "capAdd": ["SYS_PTRACE"],
  "securityOpt": ["seccomp=unconfined"]
}
```

```jsonc
// bad — sledgehammer (and runArgs is silently ignored under Docker Compose)
"runArgs": ["--privileged"]
```

The [`docker-outside-of-docker` feature](https://github.com/devcontainers/features/tree/main/src/docker-outside-of-docker)
avoids `--privileged` but is **not** a safer, scoped alternative. It
bind-mounts the host's Docker socket (`/var/run/docker.sock` →
`/var/run/docker-host.sock`), and access to a rootful Docker daemon is
root on the host: any process in the container can
`docker run -v /:/host …`. See DEVC-025.

Cite: [json_reference — capAdd, securityOpt, privileged, init](https://containers.dev/implementors/json_reference/#general-properties),
[CLI singleContainer.ts L359-L373 / dockerCompose.ts L520-L565 (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/dockerCompose.ts#L520-L565).

**When NOT to apply.** When you genuinely need `privileged` for an
isolated test environment that's never exposed to untrusted input (rare).
Document the reason inline. `runArgs` is still right for flags with no
property (`--ulimit`, `--device`, `--sysctl`) in image/Dockerfile configs.

---

## DEVC-018 — Set `"init": true` at the devcontainer.json level for proper PID 1

**What.** The dev container spec supports a top-level `"init": true`
field that adds `--init` to the container's run args. Use it (or
`"runArgs": ["--init"]`) instead of relying on the image's entrypoint
to handle signals correctly.

**Why.** Same rationale as DOCKER-006 (PID 1 / signal handling) applied
to dev containers: most editors and language servers fork child
processes; without proper init, those zombies accumulate over the
lifetime of the dev container. After a week of editing, your dev
container's process table is filled with `<defunct>` python / node /
gopls workers. Stop becomes slow because the daemon waits for a
proper SIGTERM response that never comes.

**How.**

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3-3.12-trixie",
  "init": true                              // adds --init to docker run
}
```

Equivalent via `runArgs`:

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3-3.12-trixie",
  "runArgs": ["--init"]
}
```

For `dockerComposeFile` mode, set `init: true` on the *service* in the
compose file:

```yaml
services:
  dev:
    image: myimage
    init: true
```

Cite: [containers.dev — init](https://containers.dev/implementors/json_reference/),
[compose reference — services.init](https://docs.docker.com/reference/compose-file/services/#init).

**When NOT to apply.** When the image's entrypoint already runs a real
init process (`tini`, `dumb-init`, `s6-overlay`) and you've verified it
works. Setting `init: true` on top is harmless but redundant.

---

## DEVC-019 — SSH and git credentials: forward the agent, never key files

**What.** Give the container the host's **ssh-agent socket**, never
private key files, the host's `~/.ssh` directory or its `~/.ssh/config`.
Verify host keys against **pinned** known_hosts entries, not trust on
first use. If a host gitconfig is copied in, strip anything that names a
host binary.

**Why.**

- **Key files are copyable; an agent is not.** A bind of the host `~/.ssh`
  (even read-only) exposes every private key to every process in the
  container — dependency install scripts, test code, a coding agent in
  auto-approve mode. With only the agent socket, those processes can sign
  while the container runs, but cannot copy the key out.
- **A host `~/.ssh/config` rarely works in the container.** Its
  `IdentityFile`, `Include`, `ControlPath` and `ProxyCommand` lines name
  host paths and host binaries, and a config that is a symlink into a
  dotfiles checkout dangles. It fails silently: ssh just ignores it.
- **The editor and the CLI differ.** VS Code forwards the host agent
  automatically when one is running (no setting), but only into processes
  it starts. The devcontainer CLI never forwards it — maintainer:
  "The ssh-agent forwarding is part of the Dev Containers extension and
  not part of the Dev Containers CLI. You could mount the ssh-agent's
  socket and then point SSH_AUTH_SOCK at it"
  ([devcontainers/cli#441](https://github.com/devcontainers/cli/issues/441)).
  `devcontainer exec`, `docker exec` and agents started that way see no
  agent unless you mount it (DEVC-024).
- **Socket-mount failure modes.** `${localEnv:SSH_AUTH_SOCK}` with the var
  unset or empty is a hard `docker run` error ("invalid value for
  'source': value is empty"). With a stale value (the agent restarted at a
  new path), the source path is missing. Docker re-resolves a bind source
  on every container *start*. A host agent at a stable path (e.g. a
  systemd user agent at `$XDG_RUNTIME_DIR/ssh-agent.socket`) therefore
  heals with a stop/start, while a per-login random path (`ssh-agent -s`
  under `/tmp/ssh-XXXX/`) needs a container recreate every time.
- **Read-only known_hosts alone breaks.** With the default
  `StrictHostKeyChecking ask`, a host missing from a read-only file fails
  non-interactively with "Host key verification failed". Switching to
  `accept-new` on a file that can never be written makes every connection
  a fresh trust-on-first-use.
- **Copied gitconfig pitfalls.** `credential.helper` values name host
  binaries (or are the blank `helper =` reset some tools write, which
  wipes the helper the editor injects). `core.pager`, `pager.*` and
  `interactive.diffFilter` (e.g. `delta`) name host binaries, so
  `git log` / `git add -p` break in the container.

**How.**

```jsonc
{
  "mounts": [
    // the host's agent, never its key files; unset on the host → /dev/null (no agent)
    "source=${localEnv:SSH_AUTH_SOCK:/dev/null},target=/ssh-agent.sock,type=bind",
    // container-owned ~/.ssh so known_hosts is writable and survives rebuilds
    "source=myrepo-ssh-${devcontainerId},target=/home/vscode/.ssh,type=volume",
    // hosts the host already trusts, read-only, as a second trust file
    "source=${localEnv:HOME}${localEnv:USERPROFILE}/.ssh/known_hosts,target=/home/vscode/.ssh/known_hosts.host,type=bind,readonly",
    // pinned keys committed to the repo (e.g. GitHub's published host keys)
    "source=${localWorkspaceFolder}/.devcontainer/ssh_known_hosts,target=/etc/ssh/ssh_known_hosts,type=bind,readonly"
  ],
  // containerEnv, not remoteEnv: docker exec / agent processes must see it (DEVC-023)
  "containerEnv": { "SSH_AUTH_SOCK": "/ssh-agent.sock" },
  "initializeCommand": ".devcontainer/initialize",
  "onCreateCommand": "sudo chown vscode:vscode /home/vscode/.ssh",
  "postCreateCommand": ".devcontainer/post-create.sh",
  "postStartCommand": ".devcontainer/post-start.sh"
}
```

`.devcontainer/ssh_known_hosts` — generate from the provider's API and
check it against the fingerprints it publishes. Refresh it when the
provider rotates keys:

```bash
# source: https://api.github.com/meta (ssh_keys) — verify against GitHub's published fingerprints
curl -fsSL https://api.github.com/meta | jq -r '.ssh_keys[] | "github.com " + .' > .devcontainer/ssh_known_hosts
ssh-keygen -lf .devcontainer/ssh_known_hosts   # ed25519 must read SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU
```

`.devcontainer/initialize` (host, POSIX) — make the bind sources exist
and fail loudly on a broken agent variable:

```sh
#!/bin/sh
set -eu
[ -d "$HOME/.ssh" ] || mkdir -m 700 "$HOME/.ssh"
[ -d "$HOME/.ssh/known_hosts" ] && { echo "$HOME/.ssh/known_hosts is a directory" >&2; exit 1; }
[ -f "$HOME/.ssh/known_hosts" ] || : > "$HOME/.ssh/known_hosts"
if [ "${SSH_AUTH_SOCK+set}" = set ]; then
  [ -n "$SSH_AUTH_SOCK" ] || { echo "SSH_AUTH_SOCK is set but empty — docker rejects an empty bind source; unset it or start an agent" >&2; exit 1; }
  [ -S "$SSH_AUTH_SOCK" ] || { echo "SSH_AUTH_SOCK=$SSH_AUTH_SOCK is not a live socket (stale agent env?)" >&2; exit 1; }
else
  echo "initialize: warning: no SSH agent on the host; ssh in the container will have no key" >&2
fi
```

`post-create.sh` (container, once) and `post-start.sh` (container, every
start) — warn, never fail:

```sh
# post-create.sh
chmod 700 ~/.ssh
if [ ! -e ~/.ssh/config ]; then   # written once; the volume keeps later hand edits
  printf 'UserKnownHostsFile ~/.ssh/known_hosts ~/.ssh/known_hosts.host\n' > ~/.ssh/config
  chmod 600 ~/.ssh/config
fi
[ -S /ssh-agent.sock ] || echo "post-create: WARNING no host SSH agent mounted" >&2

# post-start.sh
if [ -S "$SSH_AUTH_SOCK" ]; then
  rc=0; ssh-add -l >/dev/null 2>&1 || rc=$?
  case "$rc" in
    2) echo "post-start: agent socket is dead (host agent restarted) — stop and start the container" >&2 ;;
    1) echo "post-start: host agent has no keys loaded — run ssh-add on the host" >&2 ;;
  esac
fi
```

`/etc/ssh/ssh_known_hosts` is in the default `GlobalKnownHostsFile`, so
the pinned keys verify even with `StrictHostKeyChecking yes`. Test it:
`ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -T git@github.com`.

**Commit signing** works through the same agent with no host paths:
`git config gpg.format ssh` plus
`git config user.signingKey "key::ssh-ed25519 AAAA… comment"` (the
public key, `key::`-prefixed; the private half stays in the agent).

**Copying a host gitconfig in** (only if you must, e.g. for identity):
flatten it with `git config --global --includes --list` captured into a
variable (fail if git exits non-zero). Drop `credential.helper`,
`credential.*.helper`, `core.pager`, `pager.*` and
`interactive.difffilter` — git prints section and key names lowercased.
Write valueless boolean entries (a bare `section.key` line) as `true`.
Guards like "set only if unset" must read with
`git config --global --includes --get <key>`, or they miss values that
come through `include.path`.

**Platform notes.**

- **Windows:** the OpenSSH agent is the named pipe
  `\\.\pipe\openssh-ssh-agent`, which cannot be bind-mounted into a Linux
  container. Only VS Code bridges it. `SSH_AUTH_SOCK` is normally unset
  there, so the `:/dev/null` default applies.
- **Docker Desktop (Mac/Linux):** the host agent is exposed to containers
  at `/run/host-services/ssh-auth.sock`. Bind that path instead of
  `${localEnv:SSH_AUTH_SOCK}`.

Cite: [VS Code — sharing git credentials](https://code.visualstudio.com/remote/advancedcontainers/sharing-git-credentials),
[devcontainers/cli#441](https://github.com/devcontainers/cli/issues/441),
[ssh_config(5) — StrictHostKeyChecking, UserKnownHostsFile, GlobalKnownHostsFile](https://man.openbsd.org/ssh_config),
[GitHub's SSH key fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints),
[git-config — gpg.format, user.signingKey](https://git-scm.com/docs/git-config#Documentation/git-config.txt-usersigningKey),
[Docker Desktop — SSH agent forwarding](https://docs.docker.com/desktop/features/networking/networking-how-tos/),
[Win32-OpenSSH agent pipe](https://github.com/PowerShell/openssh-portable/blob/9a43b12c3d1dcb9b742d6b65e5f23d8022017a62/contrib/win32/win32compat/ssh-agent/agent.c#L50).

**When NOT to apply.** Containers that never talk to a git remote or SSH
host (CI builds that clone before the container starts). Codespaces,
which injects its own git credentials. The agent-socket rule itself has
no exception worth taking: if a container truly needs a key (a
deploy-only machine key), inject that one key as a secret for that job —
never the developer's host keys. Note that a mounted Docker socket makes
all of this moot (DEVC-025).

---

## DEVC-020 — Use the `secrets` property to declare recommended secret names

**What.** The top-level `secrets` property ("Recommended secrets for this
dev container" in the spec schema) names the environment variables a
contributor should supply, with optional `description` and
`documentationUrl`. It stores no values, it is a recommendation rather
than a requirement, and only some tools act on it:

| Tool | What it does with `secrets` |
|---|---|
| **GitHub Codespaces** | Lists the names on the "New with options" create page with an input box for any the user hasn't stored; entering a value is optional. Stored Codespaces secrets are injected as env vars. |
| **devcontainer CLI** | Ignores the property entirely — it never reads `secrets` and never fails for a missing one. |
| **Other consumers** | Informational: onboarding docs, editor tooltips. |

**Why.** It is the documented, discoverable place to say "this project
needs `OPENAI_API_KEY`", distinct from the plumbing (DEVC-008). Don't
rely on it for enforcement: no tool refuses to start the container when a
listed secret is missing, so a missing value still surfaces deep inside
the app unless your own script checks for it.

The CLI's separate secrets mechanism is `--secrets-file <json>`
(accepted by `devcontainer up` and `devcontainer run-user-commands`). It
injects the file's key/value pairs into the environment of **lifecycle
commands** (`onCreateCommand` … `postAttachCommand`) and the dotfiles
install, and masks the values in its log output. It does **not** set
them in `containerEnv`, so they are absent from `devcontainer exec`,
`docker exec` and the editor's terminals.

**How.**

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3-3.14-trixie",
  "secrets": {
    "OPENAI_API_KEY": {
      "description": "OpenAI API key for the inference module",
      "documentationUrl": "https://platform.openai.com/api-keys"
    },
    "GITHUB_TOKEN": {
      "description": "GitHub PAT with repo + read:packages — needed for private deps"
    }
  },
  // local plumbing (DEVC-008): the value the running container sees
  "containerEnv": {
    "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}"
  },
  // fail loudly yourself — no tool enforces the declaration
  "postCreateCommand": "test -n \"$OPENAI_API_KEY\" || { echo 'OPENAI_API_KEY is not set on the host' >&2; exit 1; }"
}
```

Secrets needed only during setup (e.g. a token for `uv sync` against a
private index) can come from a gitignored file via the CLI:

```bash
# .secrets.json (gitignored): { "GITHUB_TOKEN": "..." }
devcontainer up --workspace-folder . --secrets-file .secrets.json
```

Cite: [spec schema — secrets](https://github.com/devcontainers/spec/blob/main/schemas/devContainer.base.schema.json),
[GitHub — specifying recommended secrets](https://docs.github.com/en/codespaces/setting-up-your-project-for-codespaces/configuring-dev-containers/specifying-recommended-secrets-for-a-repository),
[CLI `--secrets-file` options (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/devContainersSpecCLI.ts#L172),
[lifecycle env injection](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-common/injectHeadless.ts#L518),
[log masking](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/devContainers.ts#L302-L307).

**Distinction from DEVC-008.**

| Mechanism | What it does | Reaches |
|---|---|---|
| `secrets` (top-level) | Declares recommended names + metadata. No values. | Codespaces create page; nothing locally |
| `containerEnv` + `${localEnv:...}` | Copies a host env var into the container at create time. | Every process in the container |
| `--secrets-file` (CLI) | Supplies values for setup only. | Lifecycle commands + dotfiles install |
| `mounts` of credential files | File-mounted secret material at a fixed path. | Anything that can read the path |

**When NOT to apply.**

- Single-developer projects where the secret-handling story is "I set the env var in my shell profile." `${localEnv:...}` alone is fine.
- For *non-secret* config (log levels, feature flags). Use `containerEnv` with literal values or `${localEnv:...}` — `secrets` is for things actually sensitive.

## DEVC-021 — Commit `devcontainer-lock.json` for reproducible feature versions

**What.** The dev container CLI generates `devcontainer-lock.json`
(stable and on-by-default since CLI v0.87.0), pinning each referenced
Feature to a `@sha256` digest plus integrity hash. Commit it, and use
`--frozen-lockfile` in CI.

**Why.** Features referenced by a floating tag (`ghcr.io/.../node:1`)
resolve to whatever the latest matching publish is at build time, so two
contributors — or CI vs a laptop — can silently get different Feature
versions, reintroducing "works on my machine." The lockfile pins the
exact resolved digests so every rebuild is identical; `--frozen-lockfile`
fails the build if the lock is stale rather than silently re-resolving.
The lock covers published Features only: "Local features and the
deprecated GitHub releases features are not recorded in the lockfile"
([lockfile spec](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainer-lockfile.md)),
so a `./`-referenced Feature is pinned only by what's committed in the repo.

**How.**

```jsonc
// devcontainer.json
"features": {
  "ghcr.io/devcontainers/features/node:1": {}
}
```

```bash
devcontainer build --workspace-folder .                  # writes devcontainer-lock.json
devcontainer build --workspace-folder . --frozen-lockfile  # CI: fail on drift
```

Reinforces DEVC-011 (pin the base / avoid ambiguous resolution) at the
Feature layer.

**When NOT to apply.** A devcontainer that uses no Features (a plain
pinned image) has nothing to lock. Otherwise commit it — there's no
downside to reproducibility here.

---

## DEVC-022 — Declare `hostRequirements.gpu` for GPU dev containers

**What.** When a dev container needs a GPU (ML work, CUDA builds),
declare it with `"hostRequirements": { "gpu": "optional" }` (or `true`,
or `{ "cores": ..., "memory": ... }`) so tooling can schedule onto a
capable host and surface the requirement.

**Why.** Without the declaration, a GPU-dependent container launches on a
host with no GPU and fails opaquely at first CUDA call — far from the
obvious cause. Declaring the requirement lets Codespaces/orchestrators
pick a suitable machine and gives a contributor a clear up-front signal
about what the project needs.

**How.**

```jsonc
"hostRequirements": { "gpu": "optional" }   // "optional" = use if present, don't block
```

Don't add `"runArgs": ["--gpus", "all"]` next to it. The devcontainer
CLI's `--gpu-availability` defaults to `detect`: when `hostRequirements.gpu`
is `true` or `"optional"`, it checks `docker info` for an nvidia runtime
and adds `--gpus all` itself. A hard-coded `--gpus all` makes the
container fail to start on GPU-less hosts, which defeats `"optional"`.
Force the flag from the command line when detection is wrong:
`devcontainer up --gpu-availability all` (or `none`).

Cite: [json_reference — hostRequirements](https://containers.dev/implementors/json_reference/#host-requirements),
[CLI `--gpu-availability` (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/devContainersSpecCLI.ts#L140),
[CLI singleContainer.ts L329-L336 — adds `--gpus all`](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/singleContainer.ts#L329-L336).

**When NOT to apply.** Containers with no GPU workload. Note runtime GPU
passthrough is still host/OS-dependent (native Linux, or WSL on Windows),
so the declaration documents intent but doesn't guarantee a GPU appears —
say so in the project's setup notes.

---

## DEVC-023 — `containerEnv` for anything non-editor processes need; `remoteEnv` only for editor/tool sessions

**What.** `containerEnv` is set on the Docker container itself, so
**every** process sees it: `docker exec`, `devcontainer exec`, coding
agents, services started by entrypoints. `remoteEnv` is applied only to
processes the dev container tool spawns (the editor's server and
terminals, lifecycle commands, `devcontainer exec`). Put variables in
`containerEnv` unless they must be computed from the running container's
environment. `${containerEnv:VAR}` is valid **only** in `remoteEnv`.

**Why.**

- An agent or script started with plain `docker exec` never sees
  `remoteEnv`. `SSH_AUTH_SOCK`, `UV_PYTHON_PREFERENCE` or a `PATH` addition
  set there works in the editor terminal and silently doesn't in the
  agent's shell.
- `${containerEnv:VAR}` is resolved after the container is running,
  and only for `remoteEnv`. Inside `containerEnv` it is not substituted,
  so `"PATH": "${containerEnv:PATH}:/opt/tool/bin"` in `containerEnv`
  sets a broken `PATH` on the container (no `/usr/bin`) and
  every process loses its tools.
- The spec itself says: "We recommend using containerEnv (over remoteEnv)
  as much as possible since it allows all processes to see the variable
  and isn't client-specific." The trade-off: `containerEnv` is static for
  the life of the container — changing it needs a rebuild.

**How.**

```jsonc
{
  "containerEnv": {
    "SSH_AUTH_SOCK": "/ssh-agent.sock",     // seen by docker exec / agents too
    "UV_LINK_MODE": "copy"
  },
  "remoteEnv": {
    // needs the container's own PATH — only valid here
    "PATH": "${containerEnv:PATH}:/home/vscode/.local/bin"
  }
}
```

If non-editor processes also need a `PATH` addition, set it in the image
(`ENV PATH=/opt/tool/bin:$PATH`) instead, where the base `PATH` is known.

Cite: [json_reference — containerEnv / remoteEnv](https://containers.dev/implementors/json_reference/#general-properties),
[json_reference — `${containerEnv:VAR}` is a remoteEnv-only variable](https://containers.dev/implementors/json_reference/#variables-in-devcontainerjson),
[CLI — containerEnv substituted from host env only (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/devContainersSpecCLI.ts#L525),
[`${containerEnv:…}` resolved for remoteEnv after start](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-common/injectHeadless.ts#L345-L347).

**When NOT to apply.** Values that are deliberately editor-only, or that
change often enough that a rebuild per change is unacceptable — those
belong in `remoteEnv`, with the understanding that `docker exec` won't
see them.

---

## DEVC-024 — Headless configs must do what the editor does for you

**What.** VS Code's Dev Containers extension performs several setup steps
that are **not** part of the spec and that the devcontainer CLI does not
do. A config that is ever started without the editor — `devcontainer up`
from a script, CI, coding agents via `devcontainer exec` / `docker exec`
— must implement them itself.

| Behavior | VS Code | devcontainer CLI | What the config must do |
|---|---|---|---|
| SSH agent forwarding | automatic when a host agent runs, for its own processes | never | bind the agent socket + `containerEnv.SSH_AUTH_SOCK` (DEVC-019) |
| Copy host `.gitconfig` | automatic on startup | never | copy / flatten it in `initializeCommand` + mount, or set identity in `postCreateCommand` (DEVC-019 lists what to strip) |
| known_hosts | not handled | not handled | pin keys in `/etc/ssh/ssh_known_hosts` (DEVC-019) |
| GPG agent forwarding | automatic when configured on the host | never | prefer SSH signing through the agent (DEVC-019) |
| `forwardPorts` / `portsAttributes` | forwards on localhost | ignored | `appPort` (published as `127.0.0.1:P:P`) (DEVC-016) |
| `waitFor` background hooks | attaches after `waitFor`, rest in background | runs all hooks synchronously | nothing — but don't assume background timing (DEVC-004) |

**Why.** The editor makes a config look complete: git identity, pushes
and ports all work in its terminal. The same container driven by the CLI
or an agent has no git identity, no agent, and no ports, and fails with
unrelated-looking errors ("Please tell me who you are", "Permission
denied (publickey)", connection refused). Maintainer on the CLI: "The
ssh-agent forwarding is part of the Dev Containers extension and not
part of the Dev Containers CLI."

**How.** Test the config the way it runs headless:

```bash
devcontainer up --workspace-folder . --remove-existing-container
devcontainer exec --workspace-folder . sh -c 'git config user.email && ssh-add -l && echo "$SSH_AUTH_SOCK"'
docker exec -u vscode "$(docker ps -q --filter label=devcontainer.local_folder="$PWD")" env | grep SSH_AUTH_SOCK
```

Each step VS Code would have done needs an explicit mount, variable or
lifecycle command. Since the editor adds its own on top, these don't
conflict.

Cite: [VS Code — sharing git credentials](https://code.visualstudio.com/remote/advancedcontainers/sharing-git-credentials),
[devcontainers/cli#441](https://github.com/devcontainers/cli/issues/441),
[CLI — no gitconfig / known_hosts / GPG handling; forwardPorts only merged (v0.89.0)](https://github.com/devcontainers/cli/blob/v0.89.0/src/spec-node/imageMetadata.ts#L192-L209).

**When NOT to apply.** Configs only ever opened in VS Code by a human.
Codespaces, which provides its own credential plumbing.

---

## DEVC-025 — A Docker socket in the container is root on the host — make it an explicit choice

**What.** Mounting the host's Docker socket — directly or through the
`docker-outside-of-docker` feature, which binds `/var/run/docker.sock` to
`/var/run/docker-host.sock` — gives every process in the container
root-equivalent control of the host when the daemon is rootful. Treat it
as a documented, accepted risk, or don't mount it.

**Why.** Docker's own docs: "The `docker` group grants root-level
privileges to the user." Through the socket any process can run
`docker run --rm -v /:/host …` and read or write any host file, including
the SSH keys and tokens you carefully kept out of the container
(DEVC-006, DEVC-019). A coding agent in an auto-approve / bypass-
permissions mode runs arbitrary commands without review. With the socket
present, every other credential boundary in the config is moot: the
agent is one command away from host root. DooD is not "scoped to
Docker": for a rootful daemon, Docker access *is* host root.

**How.**

1. Don't add the socket by default. Most dev loops need it only for
   `docker build` or testcontainers.
2. When needed, prefer a boundary that isn't host root:
   - a **rootless** Docker daemon on the host (the socket then maps to an
     unprivileged host user),
   - a **remote builder** (`docker buildx create --driver remote`, a CI
     builder, or a VM) for image builds,
   - Docker-in-Docker (`docker-in-docker` feature) when isolation matters
     more than speed. It needs `privileged`, so it isolates the *host
     daemon* but not the kernel.
3. If you keep DooD on a rootful daemon, say so where contributors will
   see it:

```jsonc
{
  "features": {
    // ACCEPTED RISK: host Docker socket = root on the host. Any process in this
    // container (including agents in bypass mode) can `docker run -v /:/host`.
    "ghcr.io/devcontainers/features/docker-outside-of-docker:1": { "moby": false }
  }
}
```

Cite: [Docker — manage Docker as a non-root user](https://docs.docker.com/engine/install/linux-postinstall/),
[docker-outside-of-docker mounts](https://github.com/devcontainers/features/blob/47406487f9b4965e4f9865f20b86805b1e2d5c0f/src/docker-outside-of-docker/devcontainer-feature.json#L67-L73),
[Docker — rootless mode](https://docs.docker.com/engine/security/rootless/).

**When NOT to apply.** Single-user machines where the container user is
already trusted with host root (it's your laptop, you're in the `docker`
group anyway) and no autonomous agent runs inside. Even then, write the
comment: the next contributor or agent config may not share that
assumption.

---

## DEVC-026 — Pin dev container base images to image-major + language + OS, or a digest

**What.** The `mcr.microsoft.com/devcontainers/*` images publish compound
tags `<image-major>-<language-version>-<os>` (e.g. `python:3-3.14-trixie`,
`javascript-node:5-24-trixie`) alongside short tags (`python:3.14`,
`javascript-node:24`). Use the compound tag, or a digest, not the short
tag.

**Why.** Short tags float across **image major versions** (breaking
changes to the image's tooling and users) **and OS releases**. The python
image's 1.x releases shipped only bookworm/bullseye variants, while
2.x+ make trixie the default. The same `python:3.14`-style tag silently
moved Debian release underneath the project. Features' OS support changes
with the OS: `docker-outside-of-docker` fails its install on Debian trixie
unless `"moby": false` is set ("The 'moby' option is not supported on
debian 'trixie' …"; `moby` defaults to `true`). A floating base tag can
therefore break a container build with no change in the repo.

**How.**

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3-3.14-trixie",
  "features": {
    // trixie: moby packages unavailable — required, or install.sh exits 1
    "ghcr.io/devcontainers/features/docker-outside-of-docker:1": { "moby": false }
  }
}
```

For full reproducibility pin the digest (`…:3-3.14-trixie@sha256:…`) and
let Dependabot / Renovate bump it. When you do change the OS, re-check
every feature's options against the new release.

Cite: [devcontainers/images python manifest (tag scheme)](https://github.com/devcontainers/images/blob/c04ecb19a95e23cf7a4275993cdb3119e9f97c60/src/python/manifest.json),
[python image history 1.0.0 vs 2.0.2](https://github.com/devcontainers/images/blob/c04ecb19a95e23cf7a4275993cdb3119e9f97c60/src/python/history/2.0.2.md),
[docker-outside-of-docker install.sh L210-L214 — trixie guard](https://github.com/devcontainers/features/blob/47406487f9b4965e4f9865f20b86805b1e2d5c0f/src/docker-outside-of-docker/install.sh#L210-L214),
[`moby` option default](https://github.com/devcontainers/features/blob/47406487f9b4965e4f9865f20b86805b1e2d5c0f/src/docker-outside-of-docker/devcontainer-feature.json#L4-L21).

**When NOT to apply.** Throwaway or exploratory containers where picking
up the newest OS automatically is the point. Even then, expect feature
option breakage on OS switches.

---
