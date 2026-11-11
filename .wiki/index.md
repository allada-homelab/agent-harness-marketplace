---
okf_version: "0.2"
---

# Gotcha

* [annotate() resets parser-set injected flags on non-system rows](./annotate-wipes-parser-injected.md) - annotate() in transcripts.py clears injected on every non-system row outside its target set; keep harness-injected turns as role=system or the flag is wiped.
* [Artifacts live beside dsh sessions, not inside them](./artifacts-live-beside-dsh-sessions.md) - Artifacts go in $DSH_HOME/artifacts/<key>/, a sibling of sessions/ (never inside sessions/<key>/), keyed like dsh's projectKey; dsh's chatfile viewer must allowlist that root.
* [bin/check.sh fails on macOS without timeout binary](./check-sh-fails-on-macos-without-timeout.md) - bin/check.sh test suite fails on macOS hosts lacking timeout/gtimeout, though the fallback path passes; check assumes timeout exists to assert the fallback is reachable.
* [Chrome's IsolateSandboxedIframes silences deferred errors in headless probes](./chrome-isolates-sandboxed-iframes-from-virtual-time.md) - Chrome's sandboxed iframe isolation (`IsolateSandboxedIframes`) blocks `--virtual-time-budget`, silencing deferred errors; fix with `--disable-features=IsolateSandboxedIframes`.
* [Compaction summaries quote earlier prompts; substring dedupe drops real ones](./compaction-summary-substring-dedupe.md) - parse_claude drops queued prompts that a user record repeats; a compaction summary quotes every earlier prompt, so match exact or start/end, never substring, or real prompts vanish.
* [Concurrent transcript ingest --rebuild orphans the database](./concurrent-ingest-rebuild-orphans-db.md) - transcripts.py ingest exits 75 'another ingest is running' since 0.9.0: an ingest.lock flock refuses a second run. Before 0.9.0 a concurrent --rebuild unlinked the live db and lost work.
* [Controlled headless claude -p runs for skill measurement](./claude-p-controlled-skill-runs.md) - Measure a skill instruction with claude -p --tools '' --strict-mcp-config and no --bare: without strict MCP, an auth-reminder leaks into output; --bare fails under OAuth login.
* [dsh session.v4 tool results carry the result at message level](./dsh-v4-tool-result-shape.md) - dsh session.v4 tool/result rows hold the result on the message itself, so a v3-only parser stores empty text and no call link; read the message-level form too.
* [Installed skill edits revert on reinstall — edit the marketplace source, not the installed copy](./installed-skill-edits-revert-on-reinstall.md) - Editing ~/.dsh/profiles/web/node_modules/@allada-homelab/<m>/skills/<s>/SKILL.md is ephemeral: a reinstall re-creates it from modules/<m>/ in agent-harness-marketplace.
* [Multiple modules' pytest tests run in one session—conftest imports collide](./module-tests-share-one-pytest-session.md) - pytest collects modules/*/test/ in one session, so from conftest import X resolves to the first conftest.py on sys.path; load shared data by path or put it in a sibling module instead.
* [New skill descriptions cost pi tokens per request](./new-skill-costs-pi-tokens-per-turn.md) - Skill metadata is injected into every pi request; longer descriptions add recurring per-turn token cost that shipped unmeasured and must be audited in pin-bump PRs.
* [Parallel pr-flow starts in one repo fail on git locks — start now flocks a lock](./pr-flow-start-serializes.md) - Parallel pr-flow start in one repo races git's no-retry locks (.git/config, commit-graph-chain.lock under fetch.writeCommitGraph); cmd_start now flocks pr-flow-start.lock in common_dir.
* [Plugin agents ignore hooks, mcpServers and permissionMode](./plugin-agents-ignore-hooks-and-permission-mode.md) - Claude Code ignores hooks, mcpServers and permissionMode in plugin agent frontmatter, so a module agent's limits must be enforced by the skill that dispatches it.
* [pr-flow merge closes PRs stacked on the merged branch](./pr-flow-merge-closes-stacked-prs.md) - pr-flow teardown (and watch --merge) push-deletes the branch on origin, and GitHub then closes every PR based on it; retarget stacked PRs to main before merging.
* [pr-flow teardown runs devc down before removing the worktree](./pr-flow-teardown-runs-devc-down.md) - Agent worktree dev containers, images and per-worktree volumes leak after git worktree remove; pr-flow teardown now runs devc down first (PR_FLOW_DEVC overrides the binary).
* [pr-flow watch counts a superseded CANCELLED run as a failure](./pr-flow-watch-false-red-on-superseded-cancelled.md) - pr-flow watch exits checks-failed on a CANCELLED check that a workflow concurrency group superseded; live_checks drops a CANCELLED run when a later run of the same workflow job exists.
* [pr-flow watch crashes when its worktree is removed mid-poll](./pr-flow-watch-dies-if-worktree-removed.md) - pr-flow watch runs git and gh with the PR worktree as cwd; removing that worktree while a watch polls kills it with a traceback, which a piped exit code hides.
* [pr-flow watch false-green on delayed CI](./pr-flow-watch-false-green-on-delayed-ci.md) - Before 0.2.21 pr-flow watch called zero Actions runs 'no CI applies' and --merge merged early; 0.2.21 skips that shortcut when a workflow runs on every PR
* [Research preview verdicts need a live check](./research-run-preview-verdicts-need-live-check.md) - Research-report preview or stable verdicts can be wrong even when they claim a live test; run the command and quote its warning or its absence before acting on one.
* [skill-creator trigger harness is unreliable for measuring descriptions](./skill-creator-trigger-harness-unreliable.md) - skill-creator's run_eval.py pollutes ~/.claude/commands and under-detects triggering (0-33% vs 12/12 independently), so run it from a scratch dir and measure with claude -p stream-json.
* [SKILL.md body ~/ path: lint-skills.py fails it, tools/lint.sh passes it](./skill-body-home-path-lint.md) - lint-skills.py: absolute path '~/x' in body fails CI, though tools/lint.sh passes locally; run bin/lint-skills.py after editing a SKILL.md, because the body check is skill-only.
* [Transcript ingest FTS triggers dominate insert cost](./transcripts-fts-triggers-dominate-ingest.md) - transcripts.py ingest slowed to hours: per-row FTS5 triggers on messages cost ~100x the insert; v6 drops them and builds FTS in one pass — never reintroduce triggers, run `fts` when dirty.
* [Untrusted worktree agent CLIs need more than a permission mode](./untrusted-worktree-agent-cli-isolation.md) - A permission mode alone does not isolate an agent CLI run on untrusted PR content; claude -p and codex exec each need extra isolation flags.

# Decision

* [Dual-review posts only worth-raising findings](./dual-review-posts-only-worth-raising.md) - dual-agent-pr-review posts only blocking, non-blocking and unresolved findings as a pending draft; nits and not-worth-raising ones stay in final.md, since low tiers were noise.

# Runbook

* [Removing a module](./removing-a-module.md) - Deleting modules/<name> leaves refs the gate misses — a stale root pi exclude, smoke tests naming it, lockfile importers — so sweep them; dated records get a note, not a rewrite.
* [Run a module skill on pi without installing the package](./pi-skill-e2e-without-install.md) - pi -p --skill <checkout>/modules/<m>/skills/<s> runs a module skill on real pi without pi install; delegate_agent is absent there, so agents take the inline fallback.
