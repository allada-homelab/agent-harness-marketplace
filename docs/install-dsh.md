# Install on dsh

dsh installs per module through pnpm's `path:` fragment:

```
dsh plugin --profile <profile> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/research"
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

## Verified 2026-09-06 (dsh 0.1.1-rc.2, throwaway `DSH_HOME`, local-path installs)

Captured before the 2026-09-07 move: `dsh-module-skills` and `hook-runner-dsh`
were sibling modules of this repo at the time, installed with the same `dsh
plugin add` command shown below. On the current layout they are installed
once, by dotfiles, as `@davidallada/dsh-module-skills` and
`@davidallada/dsh-hook-runner`, not added per profile from this repo.

```
$ dsh plugin --profile e2e add "file:…/modules/dsh-module-skills"
Done in 615ms using pnpm v11.22.0
$ dsh plugin --profile e2e add "file:…/modules/hook-runner-dsh"
$ dsh plugin --profile e2e add "file:…/modules/research"
$ dsh --profile e2e --dump-config
# == @allada-homelab/dsh-module-skills
- id: module-skills
  name: '@allada-homelab/dsh-module-skills'
  config:
    dirs: []
# == @allada-homelab/hook-runner-dsh
- id: hook-runner-dsh
  name: '@allada-homelab/hook-runner-dsh'
  config:
    manifests: []
# == @allada-homelab/research
- id: module-skills-research
  name: '@allada-homelab/dsh-module-skills'
  config:
    providerName: module-skills-research
    bundles:
      - '@allada-homelab/research'
    dirs: []
```

Booting the installed bridge against that profile with a stub `ctx` listed the
skill from the installed package with its own directory as resource base:

```
PROVIDER module-skills-research [{"name":"research","rb":{"kind":"directory","path":"…/profiles/e2e/node_modules/@allada-homelab/research/skills/research"}}]
```

Before the `dsh.bundle` key was added to content modules, the same `add`
printed `declares no dsh.bundle — installed as a plain dependency, not a
profile layer` and no row appeared; `bin/check.sh` now requires the key.
