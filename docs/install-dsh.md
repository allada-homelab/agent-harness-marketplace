# Install on dsh

dsh installs per module through pnpm's `path:` fragment:

```
dsh plugin --profile <profile> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/plan-for-dummies"
```

dsh's skill provider only reads fixed roots, so an installed package's
`skills/` directory is invisible on its own, and hooks need something to run
them. Both are handled by harness-side foundation — `@davidallada/dsh-module-skills`
(the skills bridge) and `@davidallada/dsh-hook-runner` — that lives in
the maintainer's dotfiles harness layer (private) and is always installed on every
dsh profile there; this repo's install docs assume it is present. Each content
module's `dsh.bundle.patch` key (an intentionally empty `cordis.patch.yml`) is
what makes dsh treat it as a profile layer the bridge auto-discovers, rather
than a plain dependency. User-invocable skills whose body uses `$ARGUMENTS`/`$N`
also become real `/name <args>` commands through the bridge (dsh injects a
skill body verbatim otherwise).

`PreToolUse` rewrites become a deny that names the intended input, because dsh
freezes tool arguments before its pre-execute waterfall; see
`hook-contract/README.md`.

Warnings from both foundation plugins go to `process.stderr` (dsh's
`ctx.logger` does not reach journald).

## Verified 2026-09-16 (dsh 0.1.5-rc.2, throwaway `DSH_HOME`, local-path install)

This is `tests/smoke/dsh.sh`. The skills bridge and hook runner are harness-side
foundation installed by dotfiles, not from this repo, so what is proved here is
that a content module installs as a profile layer without injecting a loader row
of its own.

```
$ dsh plugin --profile e2e add "file:…/modules/plan-for-dummies"
Done in 481ms using pnpm v11.22.0
$ dsh --profile e2e --dump-config | grep allada-homelab
(none)
$ ls "$DSH_HOME/profiles/e2e/node_modules/@allada-homelab/"
plan-for-dummies
  ok   an empty cordis.patch.yml inserts no loader row for plan-for-dummies
  ok   plan-for-dummies is installed as a bundle dependency
  ok   @allada-homelab/plan-for-dummies: content module (no plugin to apply)
```

The empty `cordis.patch.yml` is the point: the module arrives as a profile
dependency the bridge auto-discovers, and `--dump-config` stays free of any
`module-skills-*` row. Before the `dsh.bundle` key was added to content modules,
the same `add` printed `declares no dsh.bundle — installed as a plain
dependency, not a profile layer`; `bin/check.sh` now requires the key.

dsh's delegation/subagent capabilities have grown a lot across the rc series
(continuable children, a `fork` backend, background subagent jobs, per-child
model selection) — see `docs/dsh-plugin-capabilities.md` for that picture.
