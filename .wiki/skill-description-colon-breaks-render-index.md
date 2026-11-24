---
type: gotcha
title: "SKILL.md description with ': ' breaks render-index.py YAML parse"
description: "render-index.py dies 'mapping values are not allowed here' on a SKILL.md description with an unquoted ': '; Claude loads it, PyYAML rejects it, so write `>-` or quote it."
tags: [skills, modules]
generated: {by: okf-wiki/scribe, at: 2026-11-15T16:38:39Z}
verified:
  - {by: okf-wiki/scribe, at: 2026-11-15T16:38:39Z, commit: e6e6e56a9d50}
sources:
  - {id: pr-185, resource: "https://github.com/allada-homelab/agent-harness-marketplace/pull/185 : local-workers moved from the Claude-only skills-marketplace"}
  - {id: session-2026-11-15, resource: "local work 2026-11-15: uv run --script bin/render-index.py --write traceback from frontmatter() -> yaml.safe_load, column 229"}
---

# SKILL.md description with ': ' breaks render-index.py YAML parse

## Symptom

`uv run --script bin/render-index.py --write` exits with a traceback ending in `yaml.scanner.ScannerError: mapping values are not allowed here` [^session-2026-11-15]. The skill itself still loads as a Claude plugin.

## What fails

A plain unquoted `description:` scalar containing `": "`, such as `...the decide MCP tool (the d3-ultra decision model: batched yes/no...)...`. Claude Code's frontmatter parser accepts it, but PyYAML reads the second colon as a nested mapping and fails at that column [^pr-185].

## What works

Use a folded scalar, with the text indented on the next line:

```
description: >-
  ...the decide MCP tool (the d3-ultra decision model: batched yes/no ...)...
```

After that rewrite `bin/check.sh` passed [^pr-185]. Quoting the whole value also works.

## Why

`bin/render-index.py` parses each skill's frontmatter with `yaml.safe_load` [^pr-185]. The Claude loader is more lenient, so a description can work in Claude and still break the repo's index build. Any skill ported from a Claude-only marketplace is exposed.

## Verify

- `bin/render-index.py` :: `yaml.safe_load`
