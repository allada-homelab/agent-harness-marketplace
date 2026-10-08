---
type: gotcha
title: Artifacts live beside dsh sessions, not inside them
description: Artifacts go in $DSH_HOME/artifacts/<key>/, a sibling of sessions/ (never inside sessions/<key>/), keyed like dsh's projectKey; dsh's chatfile viewer must allowlist that root.
tags: [dsh, artifacts, paths, modules]
generated: {by: okf-wiki/sonnet, at: 2026-10-08T17:17:48Z}
verified:
  - {by: okf-wiki/sonnet, at: 2026-10-08T17:17:27Z, commit: d81a0ab6df3d}
  - {by: okf-wiki/sonnet, at: 2026-10-08T17:17:48Z, commit: d81a0ab6df3d}
sources:
  - {resource: modules/artifacts/skills/artifacts/artifactctl.py, id: s1}
  - {resource: modules/artifacts/test/test_artifactctl.py, id: s2}
  - {resource: https://github.com/allada-homelab/agent-harness-marketplace/pull/93, id: s3}
  - {resource: https://github.com/davidallada/.davidallada-developer-setup/pull/417, id: s4}
---

# Artifacts live beside dsh sessions, not inside them

## Symptom

Artifacts put under `~/.dsh/sessions/<key>/` would be enumerated by dsh as sessions (read from its persistence code, not observed). Artifacts written elsewhere render HTML fine but PNGs and every non-HTML link are denied in the chatfile viewer.

## What fails

An `artifacts/` folder inside `sessions/<key>/`: dsh's persistence layer (`@deepseek-ai/dsh-session-persistence-jsonl`, `sessionDir = join(projectDir(root, cwd), encodeSegment(id))`) treats every entry of a project directory as a session id, so it is enumerated as a session.

A root the viewer does not know: `@davidallada/dsh-chatfile-viewer` has a fail-closed `chatfile-viewer.policy.roots` allowlist gating PNG renders and non-HTML links. HTML is not gated; it goes to dsh's Document Preview, which reads through the session filesystem with no roots check.

## What works

Write to `$DSH_HOME/artifacts/<key>/`, beside `sessions/`, with `<key>` computed by a port of dsh's `projectKey` so `~/.dsh/sessions/--home-d-GitRepos--/` pairs with `~/.dsh/artifacts/--home-d-GitRepos--/` [^s1][^s2]. `DSH_HOME` resolves like dsh-home-paths (blank counts as unset, default `~/.dsh`); `$AGENT_ARTIFACTS_DIR` still overrides. The viewer root is added in the dotfiles repo (`dsh/profiles/{web,standalone}/cordis.patch.yml`) [^s4].

## Why

Decided 2026-10-08 (modules/artifacts 0.1.5, commit 6d63eb9), replacing `~/.cache/agent-artifacts/<basename>/` [^s3]. `projectKey`: separator runs become one `-`, chars outside `[A-Za-z0-9._-]` become `~XXXX`, a leading `-` is dropped, the result is wrapped in `--` and bounded to 251 chars. Keeping the same key lets a session's artifacts be found from its project directory without touching the sessions tree.

## Verify

- `modules/artifacts/skills/artifacts/artifactctl.py` :: `project_key`
- `modules/artifacts/skills/artifacts/artifactctl.py` :: `artifacts_root`
- `modules/artifacts/test/test_artifactctl.py` :: `test_prepare_defaults_to_dsh_home_keyed_like_sessions`
