# Install on dsh

dsh installs per module through pnpm's `path:` fragment. Install the skills
bridge once per profile, then each module you want:

```
dsh plugin --profile <profile> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/dsh-module-skills"
dsh plugin --profile <profile> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/research"
```

Why the bridge: dsh's skill provider only reads fixed roots, so an installed
package's `skills/` directory is invisible on its own. Each content module's
`cordis.patch.yml` inserts one bridge row scoped to that package, and the
module's `package.json` carries `dsh.bundle.patch` so dsh treats it as a profile
layer rather than a plain dependency. User-invocable skills whose body uses
`$ARGUMENTS`/`$N` also become real `/name <args>` commands (dsh injects a skill
body verbatim otherwise).

For hooks, add `hook-runner-dsh` the same way. `PreToolUse` rewrites become a
deny that names the intended input, because dsh freezes tool arguments before
its pre-execute waterfall; see `hook-contract/README.md`.

Warnings from both plugins go to `process.stderr` (dsh's `ctx.logger` does not
reach journald).

## Verified 2026-09-06 (dsh 0.1.1-rc.2, throwaway `DSH_HOME`, local-path installs)

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
