# Install on Claude Code

```
/plugin marketplace add allada-homelab/agent-harness-marketplace
/plugin install plan-for-dummies@agent-harness-marketplace
```

Or declaratively in `.claude/settings.json` with `extraKnownMarketplaces` and
`enabledPlugins`. Narrow what a plugin contributes with `skillOverrides`.

Only modules with a `.claude-plugin/plugin.json` are Claude plugins; the pi
and dsh harness-side foundation (the skills bridge, the hook runners) lives
outside this repo and has no Claude face because Claude already reads
`hooks/hooks.json` natively.

## Verified 2026-09-16 (Claude Code CLI, marketplace added from a local checkout)

```
$ claude plugin validate .
✔ Validation passed
$ claude plugin marketplace add "$PWD"
✔ Successfully added marketplace: agent-harness-marketplace (declared in user settings)
$ claude plugin install plan-for-dummies@agent-harness-marketplace
✔ Successfully installed plugin: plan-for-dummies@agent-harness-marketplace (scope: user)
$ claude plugin list
  ❯ plan-for-dummies@agent-harness-marketplace
    Version: 0.3.1
    Scope: user
    Status: ✔ enabled
$ claude plugin details plan-for-dummies@agent-harness-marketplace
  Skills (1)  plan-for-dummies
  Always-on:   ~125 tok   added to every session
```

Run against a throwaway `CLAUDE_CONFIG_DIR`; the GitHub form of the `add`
command is the same flow once the repository is public.
