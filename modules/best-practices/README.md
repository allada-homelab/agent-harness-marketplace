# best-practices

A library of domain best-practices skills, each carrying a stable, citable
rule index, plus one interactive audit workflow. The rule skills activate on
their own when the relevant files or topics are in context; the audit is a
command: `/best-practices:containers-audit` on Claude Code,
`/skill:containers-audit` on pi, `/containers-audit` on dsh.

## What's inside

| Skill | Scope |
|---|---|
| [`containers-best-practices`](skills/containers-best-practices/) | Docker, dev containers, compose, buildx, container-side uv (`DOCKER-`, `COMPOSE-`, `DEVC-`, `BUILDX-`, `SEC-`, `UV-`) |
| [`uv-best-practices`](skills/uv-best-practices/) | uv as a Python project tool — project shape, lockfile, environments, CI, tools, Python versions, migration (`UVP-`) |
| [`python-best-practices`](skills/python-best-practices/) | Python project conventions — layout, typing, linting, testing, async, logging, packaging (`PY-`) |
| [`fastapi-best-practices`](skills/fastapi-best-practices/) | FastAPI services — structure, models, settings, dependencies, lifespan, errors, security, async DB, testing, deployment, observability (`FAPI-`, `OBS-`, `API-`) |
| [`databases-best-practices`](skills/databases-best-practices/) | SQLite (connection PRAGMAs, WAL, writer/reader split, migrations) and PostgreSQL (pool sizing, migration locking and tests, row-lock order) (`SQLITE-`, `PG-`) |
| [`repo-best-practices`](skills/repo-best-practices/) | Repository hygiene — pre-commit, Dependabot, secret scanning, task-runner/CI parity, CODEOWNERS, GitHub Actions hardening (`REPO-`) |
| [`go-best-practices`](skills/go-best-practices/) | Go — layout, errors, concurrency, `net/http`, security, modules, quality, testing (`GO-`) |
| [`grpc-best-practices`](skills/grpc-best-practices/) | gRPC — proto design, error model, deadlines, streaming, interceptors, security, tooling, performance (`GRPC-`) |
| [`meta-best-practices`](skills/meta-best-practices/) | Format spec for the library — rule IDs, severity, entry structure, authoring tools |
| [`containers-audit`](skills/containers-audit/) | Interactive scan of Dockerfile / compose / devcontainer files against the containers rules, with per-finding approval of every fix |

[`INDEX.md`](INDEX.md) is the generated flat list of every rule in the
library. Multiple skills can activate together — a Dockerfile for a uv-based
Python project hits both containers and uv.

What a `containers-audit` run does:

1. finds every Dockerfile, compose file and `devcontainer.json` under the
   target path (the argument, else the current directory), plus the
   `.dockerignore`, `.gitignore` and `.env` files the security rules need;
2. loads only the reference files relevant to what it found;
3. records each violation with a severity (high / medium / low, or
   needs-judgment when the file alone cannot decide) and prints one report;
4. walks the findings in severity order, asking before each fix. It never
   autofixes, never deletes or moves files, and never runs `docker`.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace`
  then `/plugin install best-practices@agent-harness-marketplace`
- pi: install the marketplace package; the skills are globbed in by the root
  manifest.
- dsh: add the bundle; the harness's skills bridge discovers the skills.

## Authoring

The library is designed to grow one domain at a time. From this directory:

```bash
tools/new-skill.sh <domain>                    # scaffolds skills/<domain>-best-practices/
tools/new-rule.sh <domain> PREFIX-001 "Title"  # appends a four-part stub + index one-liner
tools/render-index.sh                          # regenerates INDEX.md
tools/lint.sh                                  # rule-ID, orphan, dead-link and frontmatter checks
```

The format is [`CONVENTIONS.md`](CONVENTIONS.md), mirrored as the
`meta-best-practices` skill so the agent follows the same conventions when it
writes rules in-session. `tests/activation-examples.md` freezes which queries
each skill should and should not activate on. `tools/lint.sh` is the
library's own check; the marketplace gate `bin/check.sh` enforces the
portable skill contract on top and does not run it.

Rule prefixes in use: `DOCKER`, `DEVC`, `COMPOSE`, `BUILDX`, `SEC`, `UV`
(containers), `UVP` (uv), `PY` (python), `FAPI` (fastapi), `GO` (go), `GRPC`
(grpc). `FE` is reserved for a future `frontend-best-practices`.

## Provenance

A port of the `best-practices` plugin (version 0.6.0) from the maintainer's
private `allada-homelab/skills-marketplace` (MIT). What changed to make it
portable and publishable:

- `commands/containers-audit.md` became the `containers-audit` skill
  (`user-invocable`, `argument-hint`); its `allowed-tools` restriction is now
  prose in the body, tool names (`Glob`, `Edit`, `AskUserQuestion`) became
  harness-neutral wording, and the reference files it loads are named by
  their skill-relative path;
- the `HOMELAB-*` rule family and `references/homelab-caching.md` are not
  carried: they wire repositories into LAN-only cache endpoints and name
  private hostnames, which this public repo must not publish. They stay in
  the private upstream;
- four one-line rule summaries in `containers-best-practices` (DOCKER-018,
  DEVC-015, UV-007, UV-009) no longer spell out absolute or home-directory
  paths, and three in `go-best-practices` (GO-016, GO-018, GO-019) no longer
  spell the `./...` package wildcard, because the portable-skill lint reads
  both as asset paths; the exact commands and paths remain in the reference
  entries;
- three placeholder hostnames and one example CIDR in reference entries
  (grpc `security.md`, uv `environments.md` / `python-versions.md`, fastapi
  `deployment.md`) use documentation names and ranges instead of
  `.internal` / RFC1918 spellings;
- same-skill reference links are written `./references/<topic>.md` so the
  marketplace lint verifies they exist; the scaffolding template and
  `new-rule.sh` emit that form;
- "Claude" in the library prose became "the agent" / "the harness";
  `plugins/best-practices/` paths became `modules/best-practices/`.

The rule content, rule IDs and numbering, the four-part entry structure,
the severity scale and mapping table, the audit's steps and approval
discipline, and the authoring tools are unchanged.
