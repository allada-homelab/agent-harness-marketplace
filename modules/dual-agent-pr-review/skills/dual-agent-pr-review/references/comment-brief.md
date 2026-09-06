You reviewed this pull request in an earlier round. Now assess the **comments
other people and bots already left on it** — which are right, which are wrong,
and which the PR has since fixed.

## The pull request

- URL: {{PR_URL}}
- Head: {{PR_HEAD}} @ {{PR_HEAD_OID}}
- Merge base: {{MERGE_BASE}}

Your working directory is the same read-only worktree at the PR head commit.
`{{RUN_DIR}}/diff.patch`, `{{RUN_DIR}}/pr.json`, and `{{RUN_DIR}}/changed_files.txt`
are still available.

Judge every comment against **the head commit**, not against the commit the
comment was written on. A comment can be entirely correct about the code as it
stood and entirely obsolete now — that is `ALREADY_ADDRESSED`, and it is a
different answer from `INVALID`. The comment list marks threads GitHub considers
`RESOLVED` or `OUTDATED`; treat those marks as a hint about intent, never as the
answer. A thread someone resolved without changing the code is still live.

## Your own findings from the earlier round

{{SELF_FINDINGS}}

Where a comment describes a defect you also found, put your finding's id in
`overlaps_finding`. That is how we learn which human concerns the reviewers
independently rediscovered, and which ones only a human saw.

## The comments

{{COMMENTS}}

## Rules

1. **Open the code for every comment you assess.** An assessment whose
   `evidence` has no `file:line` citation you actually read is discarded.
2. Assess the *claim*, not the tone or the author. A blunt comment can be right
   and a polite one wrong. Bot comments (CodeRabbit, Copilot, linters) get
   exactly the same treatment as human ones — they are frequently confidently
   wrong, and saying so is the point of this round.
3. Do not defer to a comment because a maintainer wrote it, and do not reject one
   because it disagrees with a finding of yours. If a comment shows you were
   wrong earlier, say so in `reasoning`.
4. `NOT_A_CLAIM` is for praise, questions, approvals, and pure preference. Use it
   rather than stretching a non-assertion into a verdict.
5. Do not raise new findings about the code here. Put anything like that in
   `notes`.

## Output

Return a single JSON object matching the schema you were given. No prose outside
it, no markdown fence. One assessment per comment id you were given — no more,
no fewer.
