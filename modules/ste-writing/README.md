# ste-writing

Write prose about 80% of the way to ASD-STE100 (Simplified Technical English),
the controlled language from aerospace maintenance documentation, when the user
asks for it. The idea is Andrej Karpathy's: models know the specification well,
its constraints produce unusually clean prose, and asking for "80% of the way"
drops the parts that fight engineering vocabulary.

The skill is conservative on purpose. It fires when the user names the style
("STE", "ASD-STE100", "Simplified Technical English", "controlled language") or
runs `/ste-writing`; it does not fire on a plain "make this clearer".

## Contents

- `skills/ste-writing/SKILL.md` — the instruction: the one-sentence anchor,
  the reader sentence, and three corrections that the measurements below asked
  for. Nothing else; more measured worse.
- `skills/ste-writing/references/ste-rules.md` — the rule list, which rules the
  80% keeps and drops and why, and the measurement notes.

## Install

| Harness | Command |
|---|---|
| Claude Code | `/plugin install ste-writing@agent-harness-marketplace` |
| pi | installs with the repo package; narrow with `skills: ["!modules/ste-writing/**"]` to exclude |
| dsh | `dsh plugin --profile <p> add "github:allada-homelab/agent-harness-marketplace#vX.Y.Z&path:/modules/ste-writing"` |

Then `/ste-writing <what to write, or the text to rewrite>` on Claude Code and
dsh, `/skill:ste-writing` on pi, or ask for the style by name.

## How the instruction was chosen

The body is the winner of a measured comparison, not a transcription of the
specification. Six instruction variants (none; "write in ASD-STE100"; Karpathy's
literal "80% of the way to ASD-STE100"; the rules spelled out with the 80%
relaxations; the same plus coding-agent exemptions and nuance guardrails; the
same plus a before/after example) ran as a system-prompt suffix on seven
coding-agent writing tasks with realistic inputs: a root-cause message to a
teammate, a PR description from a diff, an explanation of a class, a README
setup section from messy notes, a debugging handoff full of uncertainty, a
recommendation with tradeoffs, and a Conventional Commits message. Each task
carried a hidden checklist of 6–9 facts a correct answer must contain. Runs
were on two model tiers (Sonnet and Haiku), graded blind by Opus on fact
recall, factual errors, hedge preservation, naturalness, scannability and
format conventions, with mechanical sentence statistics alongside.

What the first round showed (42 runs per tier):

- **The style never lost information.** Fact recall was 97–100% in every
  variant on both tiers, and every command, path and identifier survived
  verbatim. The feared failure mode, shorter sentences dropping qualifiers, did
  not materialize.
- **It cost voice, consistently.** Naturalness fell from 4.9/5 (no instruction)
  to 2.9–3.6 on Sonnet and from 4.6 to 2.9–3.7 on Haiku, for a scannability
  gain of about 0.3. Mean sentence length fell from ~12 words to ~8: the model
  treated the 20/25-word ceiling as a target. The judge's recurring complaint
  was "choppy, short subject-verb sentences that repeat the subject".
- **The medium got overridden.** A Slack message grew bold section labels; a
  request for "a few paragraphs" came back as a report. The worst task on both
  tiers was the conversational root-cause message (9 → 6 on Sonnet).
- **Spelling out the rules made it worse.** The full rule list scored the
  lowest naturalness of any variant on both tiers, below the one-sentence "80%
  of the way to ASD-STE100". The nuance guardrails did not move hedge
  preservation (4.3 with them, 4.6 without; 4.7 baseline).
- **Where it fit:** runbook, PR description and commit message held their
  baseline score under the one-sentence variant. Where it did not: the Slack
  message and the teaching explanation.

The second round (140 runs, two per cell) kept the one-sentence anchor and
compared three ways of adding the corrections the data asked for (ceilings not
targets, the medium wins, verbatim and uncertainty preserved):

| Instruction | Sonnet overall / naturalness | Haiku overall / naturalness |
|---|---|---|
| none (baseline) | 8.9 / 5.0 | 8.4 / 4.7 |
| "80% of the way to ASD-STE100" alone | 8.1 / 3.4 | 7.9 / 3.9 |
| anchor + three corrections | 8.5 / 4.1 | **8.4 / 4.2** |
| anchor + full rule list + corrections | 8.6 / 4.1 | 7.9 / 3.6 |
| no spec name; "a tired engineer on a phone" + corrections | **8.8 / 4.2** | 8.1 / 3.9 |

The corrections recover most of the lost voice at no cost in facts (97–100%)
and with zero format violations. The rule list is again the weakest on the
smaller model. The audience framing is the strongest instruction on Sonnet
but Haiku turns it choppy without the spec anchor.

The third round (112 runs) tested the combination, and the literal skill body
as it then stood, against the two round-two leaders in one batch:

| Instruction | Sonnet overall / naturalness | Haiku overall / naturalness |
|---|---|---|
| anchor + corrections | 8.5 / 4.2 | 8.4 / 4.4 |
| audience framing + corrections, no spec name | 8.9 / 4.5 | 7.8 / 4.0 |
| **anchor + audience sentence + corrections** (shipped) | 8.7 / 4.1 | **8.6 / 4.0** |
| the longer skill body (with a "20% to drop" section and a "where it fits" section) | 8.6 / 4.1 | 8.0 / 3.9 |

The shipped combination is the only variant that holds the no-instruction
score on both tiers (8.6 averaged, against 8.6 for no instruction), with the
fewest factual errors of any variant (0.7 and 1.1 per output). The longer body
cost 0.35 against it, mostly on Haiku, so the extra sections moved to the
reference file. On this judge, a reader-preference score, the style's gain is
not a higher score; it is the sentence statistics (90th-percentile sentence
length 19 → 15–18 words, sentences over 20 words 12% → 2–9%, mean 11.5 → 10–11
rather than the 8 the bare instruction produces), which is what a reader who
asks for STE is asking for, at no cost in facts or voice.

Caveats on the method: one judge model, 7 tasks, 2 samples per cell, and a
"naturalness" criterion that by construction favors ordinary prose. The
differences between the corrected variants (a few tenths) are within that
noise; the differences between corrected and uncorrected (0.5–1.5 on
naturalness) are not.

## Triggering

The description is deliberately two-sided: pushy on any mention of the style,
silent otherwise. Measured on Claude Code with Sonnet, 3 runs per query: four
explicit asks in different phrasings ("rewrite this in ste", "from now on
answer in Simplified Technical English", "PR description in STE style", "the
karpathy 80% ASD-STE100 thing") triggered 12/12; the two near-miss negatives
("make this clearer and shorter", "rewrite in plain english for a junior dev")
triggered 0/6. Nine further negatives (commit message, docstring style guide,
"controlled vocabulary", a file named `parts_ste.csv`, aerospace PDFs)
triggered 0/27 in a second harness whose positive detection proved unreliable,
so treat that figure as weaker evidence.

## History

0.1.0 — initial release; the instruction is the winner of the three-round
comparison described above.
