# edit-lint

A `PostToolUse` hook on `Edit|Write`. After each edit it runs the one linter that
fits the edited file and hands the findings back to the agent as context, so a
broken script or manifest is caught on the turn that wrote it instead of in CI.

| File | Linter | Notes |
|---|---|---|
| `.sh` `.bash` `.ksh`, or no extension with an sh/bash/dash/ksh shebang | `shellcheck -S warning` | zsh is skipped — shellcheck refuses it |
| `.github/workflows/*.yml` | `actionlint` | runs from the repo root so `.github/actionlint.yaml` applies |
| YAML with top-level `apiVersion:` and `kind:` | `kubeconform -ignore-missing-schemas` | adds the Datree CRD catalog; skips anything containing `{{` (Helm/Jinja); schemas are cached under `$XDG_CACHE_HOME/edit-lint/` |
| YAML under `ansible/`, `playbooks/` or `roles/`, or a playbook (`- hosts:`) | `ansible-lint --offline` | runs from the nearest `.ansible-lint`/`ansible.cfg` |
| `.js` `.mjs` `.cjs` | `node --check` | skipped in React/Preact/Solid projects (JSX in `.js`) |
| `.ts` `.mts` `.cts` under a `tsconfig.json` | `tsc --noEmit --incremental` | project-local `tsc` preferred; only errors in the edited file are reported |

It never blocks and always exits 0. A linter that is not installed, times out, or
fails for its own reasons (bad config, no network for schemas) is skipped
silently — install the linters you want; the hook never installs anything.

**JS/TS on Claude Code.** When `CLAUDECODE=1` the JS and TS rows are skipped:
Claude gets those diagnostics from the official `typescript-lsp` plugin, so this
hook would only repeat them more slowly. pi and dsh have no LSP, so they get the
`node --check` / `tsc` pass instead.

## Install

- Claude Code: `/plugin install edit-lint@agent-harness-marketplace`
- pi and dsh: enable the module; the harness hook runner discovers
  `hooks/hooks.json` in every installed module.

## Test

`bin/check.sh` runs `test/test_edit_lint.py` (stub linters on `PATH`, so it needs
none of them installed).
