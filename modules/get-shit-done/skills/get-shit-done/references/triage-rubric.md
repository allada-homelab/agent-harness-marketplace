# Triage rubric — which tier does each subtask get?

The orchestrator (you, on Opus/Fable) assigns every subtask a **model tier** and an **effort** before
fan-out. This is where GSD's efficiency comes from: a validated production split runs a strong
orchestrator over cheaper workers (Anthropic's Opus-lead + Sonnet-subagent research system beat
single-agent Opus by ~90% on their eval). Getting the tier wrong in either direction is costly — an
under-powered model on a hard task produces silently-wrong work; an over-powered model on a mechanical
task burns the budget you were trying to save.

> **Default is Opus.** Subagents inherit the orchestrator's model unless you override. So Sonnet is never
> the default — you must set `tier: "sonnet"` **explicitly** on every subtask that can take it. Omit it
> and everything runs on Opus, defeating the point.

## The three signals (combine them — no single signal routes reliably)

1. **Specifiability.** Can the subtask's instructions, inputs, deliverable, and done-criteria be written
   down *completely* up front? → down-tier candidate. If the agent must adapt strategy mid-task, notice
   its own approach failed, or weigh a tradeoff → that's *orchestration-grade reasoning*; keep it on Opus.
2. **Output verifiability.** Will a cheap downstream check (a test, a linter/doctor, schema validation,
   an exact-match, a build) catch a wrong answer? → down-tier; the gate substitutes for the model's
   judgment. If correctness is subjective or unverifiable (architecture, nuanced prose, an open-ended
   synthesis) → up-tier, because a silently-wrong cheap answer trips no alarm. *This is the single
   most-cited routing failure mode — respect it.*
3. **Task-type taxonomy** (correlates with tier):
   - **Sonnet** — classify / extract / filter / parse; bounded search & file lookup; mechanical or
     clearly-specified edits; running a test suite; code review against an explicit checklist; drafting,
     summarizing, and generating code from a complete spec.
   - **Opus** — architecture & design decisions; hard/multi-hop debugging; security-sensitive reasoning;
     ambiguity resolution; anything where a plausible-but-wrong answer is expensive.

## Effort is a separate lever — tune it *before* reaching for a bigger model

`effort` (`low` → `max`) scales reasoning within a tier. Anthropic found a *tier* upgrade beats *doubling
token budget* on the same model — but the cheap move is to raise effort first: a Sonnet subtask that's
borderline often clears at `effort: "high"` without paying for Opus. Reserve Opus for tasks that need
Opus-grade *judgment*, not merely more thinking time.

- Mechanical Sonnet work → `effort: "low"`/`"medium"`.
- Hard reasoning (Opus, or a stretch Sonnet task) → `"high"`/`"xhigh"`; `"max"` only for the genuinely hardest.

## Guardrails (each a real, measured failure mode)

- **Don't down-tier an under-specified task just because it "looks small."** Front-load the ambiguity
  yourself first — an ambiguous brief handed to Sonnet produces wrong-shaped work you then redo on Opus,
  costing more than doing it once on Opus. A subagent is only as good as its brief.
- **Don't compensate for a too-weak model with retries.** Repeated failures/retries on a Sonnet subtask
  are the signal to *escalate the tier*, not to loop.
- **Model total pipeline cost, not per-call cost.** Fan-out already multiplies spend (~4× a chat per
  agent, ~15× for a multi-agent run); a scheme that looks cheap per-call can still blow the budget by
  adding agents. Only fan out when the task's value clears the multiplier.
- **Keep Opus headroom.** Opus and Sonnet often draw from separate rate pools — keeping workers on Sonnet
  preserves orchestrator capacity even when dollar cost isn't the binding constraint.

## Worked examples

| Subtask | Tier · effort | Why |
|---|---|---|
| Add a field to a Pydantic model + update its 3 call sites | `sonnet` · `low` | Fully specifiable, verifiable (tests/typecheck), mechanical. |
| Write unit tests for an existing pure function | `sonnet` · `medium` | Spec is the function; pass/fail is the gate. |
| Migrate 40 call sites from `old_api()` to `new_api()` | `sonnet` · `medium` | Mechanical + verifiable; fan out per file/module (file-disjoint). |
| Decide the caching layer's eviction strategy | `opus` · `high` | Judgment between tradeoffs; unverifiable up front. |
| Root-cause a heisenbug across async boundaries | `opus` · `xhigh` | Adaptive, multi-hop reasoning; wrong answer is expensive. |
| Design the module boundaries for a new subsystem | `opus` · `high` | Architecture; correctness is subjective. |

Sources: Anthropic multi-agent research system; Anthropic "choosing a model"; claude-code #26179
(audit of 62 shipped agents found none that needed Opus); RouteLLM and 2026 routing field reports.
