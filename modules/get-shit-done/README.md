# get-shit-done

Method for getting a complex or fan-out task done by decomposing it and delegating each subtask to
the cheapest capable model. Ships the `get-shit-done` skill: triage rubric, workflow cookbook, and
adversarial-verification gate. Portable — describes the method in harness-neutral terms. On Claude
Code, pair it with the `get-shit-done-claude` module, whose `/get-shit-done-claude:run` command drives
the fan-out with the Workflow tool.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install get-shit-done@agent-harness-marketplace`
- pi: the whole repo installs as one package
  (`pi install git:github.com/allada-homelab/agent-harness-marketplace`); narrow with
  `settings.packages`
- dsh: `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/get-shit-done"`
