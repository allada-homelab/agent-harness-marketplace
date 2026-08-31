You previously reviewed a pull request. A second, independent reviewer reviewed
the same PR at the same commit. Your job now is to **adjudicate the disagreements
with evidence** — not to be agreeable, and not to defend your earlier position
out of consistency.

## The pull request

- URL: {{PR_URL}}
- Head: {{PR_HEAD}} @ {{PR_HEAD_OID}}

Your working directory is the same read-only worktree at the PR head commit.
`{{RUN_DIR}}/diff.patch`, `{{RUN_DIR}}/pr.json`, and `{{RUN_DIR}}/changed_files.txt`
are still available. Re-open the code. Do not adjudicate from memory of the diff.

## Round {{ROUND}} of {{MAX_ROUNDS}}

You are **{{SELF_LABEL}}**. The other reviewer is **{{OTHER_LABEL}}**.

### Your own findings from the previous round

{{SELF_FINDINGS}}

### The other reviewer's findings

{{OTHER_FINDINGS}}

### Docket — adjudicate exactly these ids

{{DOCKET}}

{{PRIOR_EXCHANGE}}

## Rules

1. **Open the cited code for every id on the docket.** A verdict whose
   `evidence` field has no `file:line` citation you actually read this round is
   discarded, and the id stays disputed.
2. **CONFIRM** means: you traced it and the failure is real as described.
   **REJECT** means: you traced it and it cannot happen — say what prevents it
   (the guard, the caller, the type, the earlier return). **REVISE** means: a
   real defect is there but the description is wrong — wrong severity, wrong
   line, or wrong mechanism. State the correction.
3. A finding the other reviewer raised that you missed is not automatically
   wrong. Missing something is the normal outcome of two independent passes;
   the whole point of this round is to catch it. Judge it on the code.
4. Equally, do not adopt a finding because the other reviewer sounds confident.
   Plausible-and-wrong is the failure mode this process exists to kill.
5. **Withdraw your own findings that do not survive re-reading.** Put their ids
   in `withdrawn`. Withdrawing is a success, not a loss.
6. Severity disagreements are real disagreements. If you agree the defect exists
   but not that it blocks the merge, use REVISE and set `severity`.
7. Do not raise new findings. If you notice one, describe it in `notes`; it will
   be handled outside this loop.

## Output

Return a single JSON object matching the schema you were given. No prose outside
it, no markdown fence. Include one verdict per docket id — no more, no fewer.
