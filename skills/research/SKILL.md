---
name: research
description: Run the research-before-acting ladder as an explicit step — scale depth to blast radius, fan out parallel read-only agents, and return a scope with a recommendation. Use when a task is unfamiliar, multi-file, or high-blast, or when choosing between options that are expensive to get wrong.
argument-hint: "[what to research]"
disable-model-invocation: true
tags: [doctrine]
---

Research: **$ARGUMENTS**

CLAUDE.md already carries the doctrine; this skill is the invocation. Follow it in order and don't skip the cheap rungs.

## 1. Check the cheap context first

Before spawning anything: session memory, this repo's `CLAUDE.md` and `docs/`, and `git log`/`git blame` on the files in question. These often answer it outright, and a migration *away* from an approach is the single most decision-relevant thing you can find. Say what you found before proceeding.

## 2. Pick the rung — depth is earned

| Blast radius | What to run |
|---|---|
| One-sentence diff (typo, rename, config flip) | Nothing. Do it. |
| Contained — single file, established pattern here | Inline prior-art check. No subagents. |
| Moderate — multi-file, or unfamiliar tech | Background codebase scout **+** a docs agent per technology touched |
| High — auth/data/migrations, new dependency, architecture, irreversible or outward-facing | Scout + docs + best-practices web agent (official, dated sources) + the premortem below |

State which rung you chose and why, in one line.

## 3. Fan out, don't serialize

Launch the agents in a single message so they run concurrently. Every one is **read-only** and returns a structured brief, never a file dump:

> **assumptions** · **affected files** (`path:line`) · **top risk** · **open question**

Model by stakes: searches, summaries and doc verification → mid tier; architecture comparison, security review, or anything where plausible-but-wrong is expensive → Opus. Never the cheapest tier for research.

Keep clarifying and planning in the foreground while they run.

## 4. Premortem (high blast radius only)

Brief one agent: *"Assume this shipped and failed, or the plan missed something. The most likely cause is __, the constraint nobody confirmed is __, the question David should be asking but isn't is __."*

Flags must be concrete and task-specific — an adjacent consumer, a past migration, a security or perf cliff. Generic "consider edge cases" filler is a **failed check**: re-brief it. Integrate load-bearing flags into the scope and say what changed; don't append a risk list.

## 5. Verify before you rely on it

Findings are hypotheses. A subagent's confident claim is not evidence — open the cited `file:line` or re-run the gate before it enters the plan. Agents over-report and contradict each other; when two disagree, go to the primary source yourself.

For anything version-specific (a config key, a flag, an API), check the **installed artifact**, not the docs. Docs lag and public schemas omit internal fields.

## 6. Synthesize into a scope

Deliver, in this shape:

- **Interpretation** — what you take the ask to be
- **Assumptions** — stated, so a wrong one is visible
- **Deliverables** and **affected files**
- **Done-criteria** — the gate that proves it
- **Recommendation** — lead with it, name the alternatives you weighed, mark one **(Recommended)** with trade-offs

Then route: low-blast and reversible → state the scope and execute. High-blast or still-ambiguous → stop and get David's call. Ask only what discovery could not answer.
