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

**How.** On most setups you don't need to do anything extra: the dev
container CLI / VS Code honors **`updateRemoteUserUID`** (default `true`)
and automatically maps the container's `remoteUser` UID/GID to the host
user's on Linux when the image already ships a `vscode` (or similar)
non-root user. The official `mcr.microsoft.com/devcontainers/*` images
do exactly this — for those, **just set `remoteUser` and let the
automatic mapping handle the rest**.

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "remoteUser": "vscode"
  // updateRemoteUserUID defaults to true — no feature needed on this image
}
```

For custom base images that don't already have a non-root user, use the
official `common-utils` feature. Note the option keys are
**`userUid` / `userGid`** (not `uid` / `gid`):

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

The literal string `"automatic"` is special-cased by the feature to mean
"detect host UID/GID at create time." Don't combine this feature with an
image that already has a UID-1000 `vscode` user — `common-utils` will
error out trying to create one that already exists.

Cite: [common-utils feature schema](https://github.com/devcontainers/features/blob/main/src/common-utils/devcontainer-feature.json),
[updateRemoteUserUID in spec](https://containers.dev/implementors/json_reference/).

Or, in a custom Dockerfile, accept build args and create the user with the
host's UID:

```dockerfile
ARG USER_UID=1000
ARG USER_GID=${USER_UID}
RUN groupadd --gid ${USER_GID} dev \
 && useradd --uid ${USER_UID} --gid ${USER_GID} --create-home --shell /bin/bash dev
USER dev
```

```jsonc
"build": {
  "dockerfile": "Dockerfile",
  "args": { "USER_UID": "${localEnv:UID}" }
}
```

**When NOT to apply.** macOS/Windows-only dev — the host file-sharing layer
abstracts UID mapping for you. Still worth doing for portability across
contributors.

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
and amd64, and integrate cleanly with the dev container lifecycle. They
also auto-skip if the tool is already present.

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

Pin versions on features (e.g. `python:1` for the feature itself, plus
`"version": "3.12"` for the language) — the feature's "version" is the
*feature* version, not the language version.

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
| `updateContentCommand` | After content is in place during create, *and* on subsequent content updates | Container | Idempotent steps that should re-run when repo content changes (uncommon) |
| `postCreateCommand` | Once per create, after content is in place | Container | Install repo deps from lockfile, wire git hooks |
| `postStartCommand` | Inside container, every start (including restart and resume) | Container | Refresh transient state, start dev services |
| `postAttachCommand` | When the editor attaches | Container | Print welcome message, open a default file |

A separate top-level **`waitFor`** field controls which hook the editor
*blocks on* before attaching (default `updateContentCommand`). If you put
critical setup in `postCreateCommand`, set `"waitFor": "postCreateCommand"`
so the editor doesn't attach to a half-set-up container. Otherwise
`postCreateCommand` runs in the background and a fast typer can hit a
"command not found" error before `uv sync` finishes.

Cite: [containers.dev — Lifecycle scripts](https://containers.dev/implementors/json_reference/#lifecycle-scripts).

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

**How.** Mount only what's needed, read-only when possible:

```jsonc
"mounts": [
  // ssh: prefer ssh-agent forwarding (set in VS Code settings) over mounting keys
  // if you must mount, mount the specific key and make it read-only
  "source=${localEnv:HOME}/.ssh/id_ed25519,target=/home/vscode/.ssh/id_ed25519,type=bind,readonly",

  // docker socket: gives root-equivalent on the host — only mount if you need it
  // and prefer docker-outside-of-docker feature for safer abstraction
  "source=/var/run/docker.sock,target=/var/run/docker.sock,type=bind"
]
```

Better: use the official features (`ssh-keys`, `aws-cli` with profile mounts)
that handle this with appropriate care.

**When NOT to apply.** Trusted, isolated dev container with no external
dependencies — but assume otherwise unless you've audited.

---

## DEVC-007 — Choose `remoteUser` vs `containerUser` consciously

**What.** Two related but distinct settings:

- `containerUser` — the user the container's *processes* run as. Equivalent to Dockerfile `USER`. **Defaults to the image's final `USER` directive** (often `root`, but for `mcr.microsoft.com/devcontainers/*` images it's already `vscode`).
- `remoteUser` — the user the editor's *remote server* (`vscode-server`) runs as. **Defaults to `containerUser`** when unset.

**Why.** The framing isn't "if you don't set these, you get root" — it's
"these override the image's defaults, and a wrong override is worse than
no override." When the base image already sets a sensible non-root
`USER`, the safest action is to set **neither** and let defaults flow
through. Setting `containerUser` overrides the image's `USER`, which can
break feature-installed users that expected the original UID.

A common mistake is forcing `containerUser: vscode` on an image whose
last `USER` was already `vscode` — usually harmless, but if a feature
later installed something owned by a different UID it can break.

A separate setting, **`userEnvProbe`** (default `loginInteractiveShell`),
controls how the editor probes the user's shell environment. On slow
shells (heavy `.bashrc`/`.zshrc` setups) this is often the culprit for
slow editor attach — set it to `loginShell` or `interactiveShell` if you
notice startup delays.

Cite: [containers.dev — remoteUser, containerUser, userEnvProbe](https://containers.dev/implementors/json_reference/).

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
  "image": "mcr.microsoft.com/devcontainers/python:3.12"
  // neither set; remoteUser defaults to containerUser, which defaults to image USER ("vscode")
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

- `"image": "mcr.microsoft.com/devcontainers/python:3.12"` — use a pre-built image.
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
concatenating both `HOME` and `USERPROFILE` env vars. Exactly one is set
on any given OS, so the concatenation produces a valid path on every
platform.

**Why.** Linux/macOS use `HOME`; Windows uses `USERPROFILE`. Plain
`${localEnv:HOME}` is empty on Windows — and an empty source in a bind
mount silently means the *root* of the host filesystem, which is a
disaster (slow, exposes everything, fails confusingly). Plain
`${localEnv:USERPROFILE}` has the symmetric problem on Linux/macOS.

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
// bad — empty source on Windows ⇒ binds host filesystem root
"source=${localEnv:HOME}/.ssh/known_hosts,target=/home/vscode/.ssh/known_hosts,type=bind,readonly"
```

This pattern appears verbatim in the
[spec's json_reference example](https://containers.dev/implementors/json_reference/)
(under "Variables in devcontainer.json"), so it's documented — but it's
a **workaround**, not a clean primitive. Spec issue
[devcontainers/spec#335](https://github.com/devcontainers/spec/issues/335)
tracks adding a proper `${localEnv:HOME_OR_USERPROFILE}` variable.

**Important caveat — Git Bash / MSYS / Cygwin on Windows.** Under these
shells, **both** `HOME` *and* `USERPROFILE` are set:

```
HOME=/c/Users/jdoe          # MSYS-style path
USERPROFILE=C:\Users\jdoe   # Native Windows path
```

The concatenation becomes `/c/Users/jdoeC:\Users\jdoe` — invalid, and
the bind mount will fail or silently target the wrong path. If your
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
non-root container user (named volumes mount root-owned by default — see
DEVC-007 / DEVC-010).

**When NOT to apply.** Single-worktree workflows where you only ever
develop on one branch at a time. Even there, the `<repo>-` prefix is
worth keeping so volumes don't collide with other projects.

---

## DEVC-014 — Mount `.venv` (and other heavy build dirs) as a named volume on macOS

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

1. **Ownership.** Named volumes mount root-owned by default. Add an
   `onCreateCommand` to chown them to the non-root user (DEVC-010 covers
   the broader idempotency need).
2. **Per-worktree.** uv (and most tools) write absolute paths into venv
   metadata, so the venv is bound to the workspace path it was created
   for. Use `${devcontainerId}` to keep one volume per worktree.

**When NOT to apply.** Linux hosts (no file-sharing overhead — bind
mounts are direct kernel-level). Throwaway containers where the cold-sync
cost of recreating the venv each time is acceptable.

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
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
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

  // Named volumes mount root-owned; chown to the non-root user on create
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
| `appPort` | Legacy. Maps a container port to the same host port. Prefer `forwardPorts`. |
| `forwardPorts` | List of container ports to surface as forwards. VS Code makes them clickable in the UI. |
| `portsAttributes` | Per-port metadata: label, `onAutoForward` ("notify" / "openBrowser" / "silent"), protocol. |
| `runArgs` | Raw `docker run` flags appended at container start. Use for things the spec doesn't model directly (capabilities, devices, sysctls). |

**Why.** `forwardPorts` + `portsAttributes` is the spec-blessed,
editor-aware way to expose ports — VS Code/JetBrains show them in the
"Ports" panel, auto-forwards them on `localhost`, and remembers them
across sessions. `appPort` is older and less flexible. `runArgs` is the
escape hatch for everything else.

**How.**

```jsonc
{
  "image": "myimage",
  "forwardPorts": [3000, 5432, 8080],
  "portsAttributes": {
    "3000": { "label": "frontend", "onAutoForward": "openBrowser" },
    "5432": { "label": "postgres", "onAutoForward": "silent" },
    "8080": { "label": "api", "onAutoForward": "notify" }
  },
  "runArgs": [
    "--init",                              // proper PID 1 (see DOCKER-006)
    "--ulimit", "nofile=65536:65536",      // raise fd limit for high-concurrency tooling
    "--cap-add", "SYS_PTRACE"              // for native debuggers
  ]
}
```

Cite: [containers.dev — forwardPorts, portsAttributes, runArgs](https://containers.dev/implementors/json_reference/).

**When NOT to apply.** When the container doesn't expose any services
(`forwardPorts` unnecessary). When the defaults are fine for `runArgs`
— don't sprinkle flags you don't need.

---

## DEVC-017 — Use `securityOpt` / `capAdd` deliberately, not by reflex

**What.** Linux capabilities, AppArmor/SELinux profiles, and seccomp
profiles control what privileged operations the container can perform.
The spec exposes these via `runArgs` (the most general) and a few
shortcut fields, plus container-level config in `dockerComposeFile` mode.

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
  "runArgs": [
    // good — add only what you need
    "--cap-add=SYS_PTRACE",
    "--security-opt=seccomp=unconfined"
  ]
}
```

```jsonc
// bad — sledgehammer
"runArgs": ["--privileged"]
```

For Docker-in-Docker / Docker-outside-of-Docker, prefer the
[`docker-outside-of-docker` feature](https://github.com/devcontainers/features/tree/main/src/docker-outside-of-docker)
over `--privileged`. It mounts the host Docker socket (which has its
own security implications — equivalent to host-root, but at least scoped
to Docker).

**When NOT to apply.** When you genuinely need `--privileged` for an
isolated test environment that's never exposed to untrusted input (rare).
Document the reason inline.

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
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "init": true                              // adds --init to docker run
}
```

Equivalent via `runArgs`:

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
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

## DEVC-020 — Use the `secrets` property to declare required secret names

**What.** The dev container spec defines a top-level `secrets` field
that names the **secret variable names** the container needs, plus
optional metadata (description, documentation URL). It does **not**
store secret values — those come from the host's credential manager
(Codespaces secrets, devcontainer CLI's `--secrets-file`, future
tooling integrations).

```jsonc
{
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "secrets": {
    "OPENAI_API_KEY": {
      "description": "OpenAI API key for the inference module",
      "documentationUrl": "https://platform.openai.com/api-keys"
    },
    "GITHUB_TOKEN": {
      "description": "GitHub PAT with repo + read:packages scopes"
    }
  }
}
```

Cite: [containers.dev json_reference — secrets](https://containers.dev/implementors/json_reference/),
[CLI support — devcontainers/cli#493](https://github.com/devcontainers/cli/pull/493).

**Why.** This is the *contract* form of secret declaration, distinct
from `${localEnv:...}` (DEVC-008). DEVC-008 says "pull a value from
the host env at create time" — but if the env var isn't set, the
container silently starts with an empty value and the failure surfaces
deep inside the app. `secrets` is the declarative version: "this
container needs these names; tool, please ensure they're set."

What different tools do with `secrets`:

- **Codespaces** — reads `secrets` to know which of the user's stored
  Codespace secrets to inject. If a required secret has no stored
  value, Codespaces prompts the user before starting the container.
- **devcontainer CLI** — reads `secrets` against a host-supplied
  secrets file (`--secrets-file`). Missing values fail container
  creation with a clear error.
- **Other consumers** — informational, but the `description` and
  `documentationUrl` show up in onboarding docs and editor tooltips.

`${localEnv:...}` is still the right mechanism for *plumbing* the
secret through to the container — the two work together:

```jsonc
{
  "secrets": {
    "OPENAI_API_KEY": {
      "description": "OpenAI API key — get one at https://platform.openai.com/api-keys"
    }
  },
  "containerEnv": {
    // declarative contract above; here's how the value flows in
    "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}"
  }
}
```

For Codespaces, the `containerEnv` line isn't needed — Codespaces
injects the value directly based on `secrets`. For the local CLI, both
the `secrets` declaration *and* the `containerEnv` plumbing are
required (the CLI doesn't inject env vars automatically based on the
`secrets` field — it only validates that the names are populated).

**How.** Full example for a project that needs three secrets:

```jsonc
{
  "name": "myapp-dev",
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "secrets": {
    "OPENAI_API_KEY": {
      "description": "OpenAI API key for the LLM module",
      "documentationUrl": "https://platform.openai.com/api-keys"
    },
    "GITHUB_TOKEN": {
      "description": "GitHub PAT with repo + read:packages — needed for private deps"
    },
    "DATABASE_URL": {
      "description": "Postgres connection string for the shared dev DB"
    }
  },
  "containerEnv": {
    "OPENAI_API_KEY": "${localEnv:OPENAI_API_KEY}",
    "GITHUB_TOKEN":   "${localEnv:GITHUB_TOKEN}",
    "DATABASE_URL":   "${localEnv:DATABASE_URL}"
  }
}
```

Local CLI invocation with a secrets file:

```bash
# .secrets.json (gitignored)
# { "OPENAI_API_KEY": "sk-...", "GITHUB_TOKEN": "ghp_...", "DATABASE_URL": "postgres://..." }

devcontainer up --workspace-folder . --secrets-file .secrets.json
```

The CLI verifies every name in `secrets` has a value in the file
(falling back to host env for unspecified names). Missing required
secrets fail with `Error: required secret <NAME> not provided`.

**Distinction from DEVC-008.**

| Field | What it does | When to use |
|---|---|---|
| `secrets` (top-level) | Declarative contract — names + metadata. No values. | Document required secrets; let tools validate they're set. |
| `containerEnv` + `${localEnv:...}` | Imperative plumbing — pull host env into container env. | Actually deliver the value to the running container (local CLI). |
| `mounts` of credential files | File-mounted secret material at a fixed path. | When the secret is a file (SSH key, GCP service account JSON), not an env var. |

The best dev containers use **`secrets` + `containerEnv:
${localEnv:...}`** together: the first declares the contract, the
second wires the value through.

**When NOT to apply.**

- Single-developer projects where the secret-handling story is "I set the env var in `~/.zshrc` and never think about it." `${localEnv:...}` alone is fine.
- When the dev container CLI version in use predates [devcontainers/cli#493](https://github.com/devcontainers/cli/pull/493) — the `secrets` field is silently ignored. The declaration still has documentation value, but no enforcement.
- For *non-secret* config (log levels, feature flags). Use `containerEnv` with literal values or `${localEnv:...}` without the `secrets` declaration — the `secrets` field is reserved for things actually sensitive.

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
"hostRequirements": { "gpu": "optional" },   // "optional" = use if present, don't block
"runArgs": ["--gpus", "all"]
```

**When NOT to apply.** Containers with no GPU workload. Note runtime GPU
passthrough is still host/OS-dependent (native Linux, or WSL on Windows),
so the declaration documents intent but doesn't guarantee a GPU appears —
say so in the project's setup notes.

---
