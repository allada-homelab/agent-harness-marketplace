# minimalist-code-review

A pragmatic, anti-over-engineering pull-request reviewer with a warm, Socratic voice. Ships the
`pragmatic-code-review` skill.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install minimalist-code-review@agent-harness-marketplace`
- pi: the whole repo installs as one package
  (`pi install git:github.com/allada-homelab/agent-harness-marketplace`); narrow with
  `settings.packages`
- dsh: `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/minimalist-code-review"`
  (after installing `dsh-module-skills` the same way once)
