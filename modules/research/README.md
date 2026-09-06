# research

Run the research-before-acting ladder as an explicit step and return a scope with a recommendation.
Ships the `research` skill (`/research <topic>` on Claude Code): checks cheap context first, picks a
depth rung by blast radius, fans out read-only agents, runs a premortem for high-blast work, and
synthesizes into interpretation / assumptions / deliverables / done-criteria / recommendation.

## Install

- Claude Code: `/plugin marketplace add allada-homelab/agent-harness-marketplace` then
  `/plugin install research@agent-harness-marketplace`
- pi: the whole repo installs as one package
  (`pi install git:github.com/allada-homelab/agent-harness-marketplace`); narrow with
  `settings.packages`
- dsh: `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#v0.1.0&path:/modules/research"`
  (after installing `dsh-module-skills` the same way once)
