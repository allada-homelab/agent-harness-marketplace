---
name: complete-tasks-mixed-tier
description: >-
  Own a piece of work end-to-end by decomposing it and fanning it out to a mixed fleet of parallel workers — local pi-run runs where a piece suits the local model, Sonnet or Opus subagents for pieces above its ceiling — while you hold the plan, gate every result on the real artifact, and synthesize. Two postures: dynamic (default, local used tactically) and local-first (local presumed, escalation earned). Use when David asks to get multi-part work done with local and cloud workers, e.g. "fan this out across local and cloud workers", "get this done with local workers, escalate what they can't", "local-first fleet". Not for a bare "fan this out" or "use subagents" with no local opt-in, local-only delegation (the delegate skill), a single well-scoped task, or benchmarking the local model (replay-eval).
harness: [claude]
---

# Complete tasks, mixed-tier: fan-out under one owner

You are the task owner: decompose the work, hold the plan, hand back the synthesis. Workers — local
or cloud, split by the active posture — execute scoped briefs in parallel and push back at their
limit. Difficulty routes the worker; you never delegate the *design*.

The `delegate` skill's rules apply unchanged to every local piece: brief structure, size floor,
parallelism, the artifact gate, security. Read it first, plus `../delegate/references/capability-map.md`.

## Delegation posture

One switch sets the routing presumption; default **`dynamic`**. A posture named in the ask pins it;
otherwise read the structure: local the default, escalation the exception ("escalate what they
can't", "save credits") → **`local-first`**; anything else → **`dynamic`**. Say which you run.

- **`dynamic` (default)** — only a clear fit goes local: bounded, decided spec, rated Reliable in
  the capability map. Borderline pieces go to a cloud worker. Burden of proof: show the piece suits
  local.
- **`local-first`** — every delegable piece starts local, borderline and unmapped included, unless it
  is above the ceiling. Burden of proof: show the piece is too hard for local — provable up front
  only by the ceiling; otherwise escalation is earned through step 5. Accepts churn to maximize local
  use.

**Above the local ceiling** (either posture): the map rates the piece Avoid, or its input can't be
cut down to a bounded extract. Design and *underspecified* work are not above the ceiling — they come
back to you to decide or spec first, which often brings them under it.

**Invariant:** posture moves only the routing presumption, never the artifact gate, escalate-last,
or owner-owns-design. `local-first` changes what you try first, not the bar a result must clear.

## The loop

1. **Own the plan.** Decompose into self-contained briefs (or take the caller's list). Settle every
   design decision before dispatch — a decided spec beats a bigger model; an open design call is
   never delegated. The **done-boundary** (green in place, committed, or a PR) comes from the ask;
   unspecified → green in place, and say so.

2. **Route each piece under the active posture:**
   - Local-suited → `pi-run` (`--read-only` when it only reads).
   - Sonnet — decided-spec work above the local ceiling, and `dynamic`'s borderline pieces.
   - Opus, sparingly — subtle debugging, adversarial review.
   - Plan, design calls, blast-radius judgement, synthesis, the final gate → **you, never delegated.**

   Cloud workers are subagents through the Agent tool with `model: sonnet` or `model: opus`, in the
   background, with the same brief discipline. A subagent starts with none of this conversation, so
   its brief carries everything. Prefer a read-only subagent type for analysis.

3. **Fan out in parallel** — independent briefs in one message, at most 4 local runs at a time.
   Parallel *writers* touch disjoint files; same-file pieces are one brief or run serially.

4. **Gate every result on the artifact** — the real `git diff` plus `git status` for untracked
   debris, the exit code, a test run you execute. **Never the worker's self-report**: a local run has
   reported a confident "52 passed" over an empty diff.

5. **Escalate last** — the same in both postures. One dispatch plus one re-brief (tighter spec,
   evidence demanded) per rung, then up: local → Sonnet → Opus → you. Before any retry or
   escalation, restore the piece's files to the gated base — including untracked strays, which
   `git checkout` won't remove — so each attempt starts clean. A dead backend is not a capability
   failure: reroute those pieces to a cloud worker, re-scoped for it.

6. **Synthesize.** Integrate the pieces, run the whole gate at the agreed done-boundary, and hand back
   one coherent result grouped by the original ask, with the local / Sonnet / Opus counts.

## Non-negotiables

- **Every brief carries a push-back clause and a real Verify line.** Push-back: "If you cannot
  complete this exactly as specified, stop and output `BLOCKED: <reason>` — do not improvise or report
  partial work as done." Verify: the repo's *actual* gate command, not "make sure it works". For test
  generation, **name every case you want** — coverage you don't name won't appear.
- **You own blast radius.** Workers don't reason about second-order effects. Gate the changed
  module's suite plus its direct consumers; at synthesis, the repo's full gate.
- **Escalation changes the worker, not the owner.** A Sonnet or Opus worker gets the same scoped brief
  and the same artifact gate — a peer executing your plan, not a co-designer.
- **Nothing is done on a worker's say-so.** Handing back means you inspected the integrated artifact.
