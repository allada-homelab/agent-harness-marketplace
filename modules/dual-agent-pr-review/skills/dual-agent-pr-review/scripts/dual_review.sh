#!/usr/bin/env bash
# Orchestrates two independent CLI code reviewers (Claude Code + Codex) over one
# PR snapshot. Deterministic plumbing only — all judgment (pairing findings,
# deciding consensus) belongs to the calling agent.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_VERSION="$(jq -r '.version // "unknown"' "$SKILL_DIR/../../package.json" 2>/dev/null || echo unknown)"
RUNS_ROOT="${DUAL_REVIEW_RUNS:-$HOME/.claude/dual-review/runs}"
WORKTREE_ROOT="${DUAL_REVIEW_WORKTREES:-$HOME/.git-worktree}"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "  $*" >&2; }

# `timeout SECONDS cmd...`, portably.
#
# macOS ships neither GNU `timeout` nor `gtimeout` unless coreutils is
# installed, so without this every agent launch dies instantly with
# "timeout: command not found" — a round that reads as an agent failure but
# never started one. Prefer the real binaries; emulate otherwise, reporting 124
# on expiry so the caller's "failed (exit N)" line is the same either way.
run_with_timeout() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"; return $?; fi
  if command -v gtimeout >/dev/null 2>&1; then gtimeout "$secs" "$@"; return $?; fi

  # No timeout binary anywhere: emulate one. The template is not optional —
  # BSD mktemp (i.e. macOS, the platform this fallback exists for) rejects a
  # bare `mktemp`. If even that fails we cannot track expiry, so run unbounded
  # rather than not at all.
  local expired
  expired="$(mktemp "${TMPDIR:-/tmp}/dual-review-timeout.XXXXXX" 2>/dev/null)" \
    || { "$@"; return $?; }

  # Job control puts the command in its OWN process group, so the watchdog can
  # signal the whole tree. This is load-bearing: without it the job shares THIS
  # shell's group, and a group-directed kill would take down the review run
  # itself. An agent launch spawns tool subprocesses, and GNU timeout kills the
  # group too (that is what --foreground opts out of), so signalling only the
  # top-level PID leaves those children running past the deadline — measured.
  local had_monitor=0; case "$-" in *m*) had_monitor=1 ;; esac
  set -m
  "$@" &
  local job=$!
  [[ $had_monitor -eq 1 ]] || set +m

  (
    sleep "$secs"
    # Record expiry BEFORE signalling. `wait` can return the instant TERM
    # lands, so inferring expiry afterwards from the watchdog still being
    # alive is a race that reports the job's 143 instead of timeout's 124.
    printf 1 > "$expired"
    # The group first; the bare PID only if the job never became a leader.
    kill -TERM -"$job" 2>/dev/null || kill -TERM "$job" 2>/dev/null
  ) &
  local killer=$!

  local rc=0
  wait "$job" 2>/dev/null || rc=$?
  [[ -s "$expired" ]] && rc=124
  kill -TERM "$killer" 2>/dev/null
  wait "$killer" 2>/dev/null || true
  rm -f "$expired"
  return "$rc"
}

# ── codex is frequently not on PATH; the Cursor ChatGPT extension ships a real one
resolve_codex() {
  if [[ -n "${CODEX_BIN:-}" ]]; then echo "$CODEX_BIN"; return; fi
  if command -v codex >/dev/null 2>&1; then command -v codex; return; fi
  local found
  found=$(ls -d "$HOME"/.cursor-server/extensions/openai.chatgpt-*/bin/*/codex \
                "$HOME"/.vscode-server/extensions/openai.chatgpt-*/bin/*/codex 2>/dev/null \
          | sort -V | tail -1) || true
  [[ -n "$found" && -x "$found" ]] || die "codex CLI not found. Install it (npm i -g @openai/codex) or set CODEX_BIN."
  echo "$found"
}

# Codex sandboxes every shell call. On Linux the only backend is bubblewrap
# (codex 0.162 dropped landlock, and features.use_legacy_landlock now panics
# with "filesystem-restricted execution requires bubblewrap"), which needs an
# unprivileged user namespace that container seccomp profiles deny. Codex then
# fails every shell command while still answering — a review with no file reads
# behind it. Probe codex itself, forced read-only. Where the sandbox cannot start
# INSIDE A CONTAINER, codex runs with --sandbox danger-full-access: the dev
# containers get no seccomp change, so the container itself is the boundary —
# codex then runs the PR's checkout with that container's credentials and
# network, which preflight says out loud. On a host there is no such boundary,
# so preflight fails instead. macOS uses Seatbelt and needs no probe.
in_container() {
  [[ -f /.dockerenv || -f /run/.containerenv || -n "${REMOTE_CONTAINERS:-}${REMOTE_CONTAINERS_IPC:-}${CODESPACES:-}" ]]
}
codex_sandbox_works() {
  [[ "$(uname -s)" == Linux ]] || return 0
  run_with_timeout 60 "$(resolve_codex)" sandbox --disable use_legacy_landlock \
    -c 'sandbox_mode="read-only"' -- true >/dev/null 2>&1
}
# Prints the --sandbox value to run codex with; dies where no safe answer exists.
codex_sandbox_mode() {
  if codex_sandbox_works; then echo read-only
  elif in_container; then echo danger-full-access
  else die "codex cannot start its sandbox here: bubblewrap needs an unprivileged user namespace, and this host denies it (on Ubuntu 24.04 load the bwrap-userns-restrict AppArmor profile). Not falling back to danger-full-access outside a container: codex would run the PR's code with your credentials."
  fi
}

require_tools() {
  command -v claude >/dev/null 2>&1 || die "claude CLI not found on PATH."
  command -v gh  >/dev/null 2>&1 || die "gh CLI not found on PATH."
  command -v jq  >/dev/null 2>&1 || die "jq not found on PATH."
  gh auth status >/dev/null 2>&1 || die "gh is not authenticated. Run: gh auth login"
  local codex_bin; codex_bin=$(resolve_codex)
  "$codex_bin" login status >/dev/null 2>&1 \
    || die "codex ($codex_bin) is not logged in. Run: $codex_bin login"
  codex_sandbox_mode >/dev/null
}

# Names why a codex round failed, from its own output. Every cause listed here
# reached the old status line as "read no files" or "exit ?", and each one has a
# different remedy, so the orchestrator should not have to grep the log for it.
codex_failure_cause() {
  local dir="$1"
  if [[ "$(cat "$dir/codex.exit" 2>/dev/null)" == 124 ]]; then
    echo "codex timed out after ${AGENT_TIMEOUT:-?}s — raise --timeout or narrow the review"; return
  fi
  # Only codex's own error lines (`ERROR:` / `<ts> ERROR <target>:` / a panic):
  # the log also carries command output, and a PR whose code says
  # `HTTPError("401 Unauthorized")` must not read as an auth failure.
  local errs
  errs=$(cat "$dir/codex.log" "$dir/codex.stdout" 2>/dev/null | grep -E '(^|[[:space:]])ERROR[: ]|panicked at' || true)
  if grep -qiE 'out of credits|insufficient_quota|quota exceeded|usage limit' <<<"$errs"; then
    echo "codex account is out of credits/quota — refill it, then re-run this round with --only codex"; return
  fi
  if grep -qiE '401 Unauthorized|not logged in|please (log|sign) in' <<<"$errs"; then
    echo "codex is not logged in (401) — run 'codex login', then re-run this round with --only codex"; return
  fi
  # A sandbox that cannot start fails each command, not codex itself; the clearest
  # trace is codex's own final answer, echoed into the log as a {"summary": line.
  local answer
  answer=$( { grep -h '^{"summary"' "$dir/codex.log" "$dir/codex.stdout"; cat "$dir/codex.raw.json"; } 2>/dev/null || true)
  if grep -qiE 'bubblewrap|use_legacy_landlock|panicked' <<<"$errs" \
     || grep -qiE 'requires bubblewrap|bubblewrap.*(unavailable|not available)' <<<"$answer"; then
    echo "codex could not start its sandbox (bubblewrap) — run preflight; it picks the right mode for this machine"; return
  fi
}

# A lower bound on successful codex commands that did more than read the run dir.
# A command that only touched $RUN_DIR (diff.patch, pr.json) read the diff, not
# the code: a run whose worktree reads were all denied once passed on four of
# those. Codex logs parallel calls as a batch — every `exec` header first, then
# the results in completion order with no header — so a result cannot be tied
# to its command; per batch, successes beyond the run-dir commands must have
# read the worktree.
codex_worktree_execs() {
  local log="$1" run_dir="$2"
  [[ -f "$log" ]] || { echo 0; return; }
  awk -v rd="$run_dir" '
    function close_hdr() { if (have) { if (index(cmd, rd)) hrd++; have = 0; cmd = "" } }
    function close_batch() { close_hdr(); if (s > hrd) n += s - hrd; s = 0; hrd = 0 }
    /^exec$/ { if (state == "res") close_batch(); else close_hdr(); have = 1; cmd = ""; state = "hdr"; next }
    /^ succeeded in / { close_hdr(); s++; state = "res"; next }
    /^ (exited|failed|declined)/ { close_hdr(); state = "res"; next }
    state == "hdr" && have { cmd = cmd $0 "\n" }
    END { close_batch(); print n + 0 }' "$log"
}

# ── preflight ────────────────────────────────────────────────────────────────
cmd_preflight() {
  require_tools
  local codex_bin; codex_bin=$(resolve_codex)
  echo "skill  : dual-agent-pr-review $MODULE_VERSION ($SKILL_DIR)"
  echo "claude : $(command -v claude) ($(claude --version 2>/dev/null | head -1))"
  echo "codex  : $codex_bin ($("$codex_bin" --version 2>/dev/null | head -1)), logged in"
  echo "gh     : authenticated"
  echo "runs   : $RUNS_ROOT"
  # Login status does not prove the account can answer: an exhausted workspace
  # still reports logged in, then fails every round. One tiny call settles it.
  local probe_dir; probe_dir=$(mktemp -d "${TMPDIR:-/tmp}/dual-review-probe.XXXXXX")
  local probe_rc=0
  ( cd "$probe_dir" && run_with_timeout 120 "$codex_bin" exec --skip-git-repo-check --ephemeral \
      --sandbox "$(codex_sandbox_mode)" --ignore-user-config -c approval_policy='"never"' \
      --output-last-message "$probe_dir/codex.raw.json" \
      "Reply with the single word OK." </dev/null >"$probe_dir/codex.stdout" 2>"$probe_dir/codex.log" ) \
    || probe_rc=$?
  echo "$probe_rc" > "$probe_dir/codex.exit"
  if [[ $probe_rc -ne 0 ]] || ! grep -qi 'ok' "$probe_dir/codex.raw.json" 2>/dev/null; then
    local cause; cause=$(AGENT_TIMEOUT=120 codex_failure_cause "$probe_dir")
    [[ -n "$cause" ]] || cause="cause unknown; its log follows: $(tail -5 "$probe_dir/codex.log" 2>/dev/null)"
    rm -rf "$probe_dir"
    die "codex could not answer a one-line probe (exit $probe_rc): $cause"
  fi
  rm -rf "$probe_dir"
  echo "codex probe : answered"
  if [[ "$(uname -s)" != Linux ]]; then echo "codex sandbox : seatbelt (macOS, read-only)"
  elif [[ "$(codex_sandbox_mode)" == read-only ]]; then echo "codex sandbox : bubblewrap (read-only probe passed)"
  else echo "codex sandbox : NONE — bubblewrap cannot start in this container, so codex runs danger-full-access; the container is the only boundary (its credentials and network are reachable from the PR's checkout)"; fi
}

# ── existing PR discussion ───────────────────────────────────────────────────
# One GraphQL call gets inline threads with their resolved/outdated state, which
# REST does not expose and which decides whether a comment is still live.
fetch_pr_comments() {
  local owner="$1" repo="$2" num="$3" out="$4"
  local raw
  raw=$(gh api graphql -F owner="$owner" -F repo="$repo" -F num="$num" -f query='
    query($owner:String!,$repo:String!,$num:Int!){
      repository(owner:$owner,name:$repo){
        pullRequest(number:$num){
          reviewThreads(first:100){ nodes{
            isResolved isOutdated path line originalLine
            comments(first:50){ nodes{ databaseId author{login} body url createdAt diffHunk } } } }
          reviews(first:100){ nodes{ author{login} body url createdAt state } }
          comments(first:100){ nodes{ author{login} body url createdAt } } } } }' 2>/dev/null) \
    || { echo '[]' > "$out"; return; }

  jq '
    def person: (.author.login // "unknown");
    [ ( .data.repository.pullRequest.reviewThreads.nodes[] | . as $t
        | $t.comments.nodes[0] | select(. != null)
        | { kind: "inline", author: person, path: $t.path, comment_id: .databaseId,
            line: ($t.line // $t.originalLine),
            resolved: $t.isResolved, outdated: $t.isOutdated,
            url: .url, created_at: .createdAt, body: .body,
            diff_hunk: (.diffHunk // ""),
            replies: [ $t.comments.nodes[1:][] | { author: person, body: .body } ] } )
    , ( .data.repository.pullRequest.reviews.nodes[] | select((.body // "") != "")
        | { kind: ("review(" + (.state|ascii_downcase) + ")"), author: person,
            path: null, line: null, resolved: false, outdated: false,
            url: .url, created_at: .createdAt, body: .body, diff_hunk: "", replies: [] } )
    , ( .data.repository.pullRequest.comments.nodes[]
        | { kind: "conversation", author: person, path: null, line: null,
            resolved: false, outdated: false,
            url: .url, created_at: .createdAt, body: .body, diff_hunk: "", replies: [] } )
    ] | sort_by(.created_at)
      | to_entries | map(.value + { id: ("PC-" + ((.key + 1) | tostring)) })
  ' <<<"$raw" > "$out"
}

render_pr_comments() {
  jq -r '
    if length == 0 then "No existing comments on this PR."
    else ( .[] |
      "### \(.id) — \(.author) · \(.kind)"
      + (if .path then " · \(.path):\(.line // 0)" else "" end)
      + (if .resolved then " · RESOLVED" else "" end)
      + (if .outdated then " · OUTDATED (written against an older commit)" else "" end)
      + (if .comment_id then " · reply-to id \(.comment_id)" else "" end)
      + "\n\(.url)\n\n\(.body)\n"
      + (if (.diff_hunk | length) > 0 then "\nCommented on this hunk:\n```diff\n\(.diff_hunk)\n```\n" else "" end)
      + (if (.replies | length) > 0 then "\nReplies:\n" + ([.replies[] | "- **\(.author)**: \(.body)"] | join("\n")) + "\n" else "" end)
      + "\n---\n" )
    end' "$1"
}

# ── related PRs ──────────────────────────────────────────────────────────────
# Two things the base branch alone does not reveal: commits on this branch that
# belong to OTHER PRs (a parent that was squash-merged leaves its original
# commits here, so the diff silently includes its work), and open PRs touching
# the same files (a finding or a "follow-up" may already be handled there).
find_related_prs() {
  local owner_repo="$1" num="$2" src_repo="$3" merge_base="$4" head_oid="$5" changed="$6" out="$7"
  local sha prs="" others
  while read -r sha; do
    others=$(gh api "repos/$owner_repo/commits/$sha/pulls" \
      --jq ".[] | select(.number != $num) | \"#\(.number) (\(if .merged_at then \"merged\" else .state end)) \(.title)\"" 2>/dev/null) || continue
    [[ -n "$others" ]] && prs+="$others"$'\n'
  done < <(git -C "$src_repo" rev-list --max-count 60 "$merge_base..$head_oid" 2>/dev/null)
  local overlapping
  overlapping=$(gh pr list --repo "$owner_repo" --state open --limit 100 --json number,title,files 2>/dev/null \
    | jq -r --argjson n "$num" --rawfile ch "$changed" '
        ($ch | split("\n") | map(select(length > 0))) as $mine
        | .[] | select(.number != $n)
        | [.files[].path | select(IN($mine[]))] as $shared
        | select(($shared | length) > 0)
        | "#\(.number) \(.title) — shares: \($shared[:5] | join(", "))\(if ($shared|length) > 5 then " …" else "" end)"' 2>/dev/null) || overlapping=""
  {
    echo "# Related pull requests"
    echo
    echo "## Other PRs whose commits are in this PR's diff"
    if [[ -n "$prs" ]]; then
      echo "These commits belong to another PR. If that PR is merged, this branch carries"
      echo "its pre-squash commits and the diff includes work that is not this PR's."
      echo
      sort -u <<<"$prs" | sed '/^$/d; s/^/- /'
    else echo "None found."; fi
    echo
    echo "## Open PRs touching the same files"
    if [[ -n "$overlapping" ]]; then sed 's/^/- /' <<<"$overlapping"; else echo "None found."; fi
  } > "$out"
  # Only a MERGED other PR means hidden stacking; an open one is a visible parent
  # or a sibling, which the base-branch check and the listing already cover.
  grep -q '(merged)' <<<"$prs"
}

# Re-review: writes prior.md (the prior run's ledger) and delta.patch (prior head
# → current head) into run_dir, and prints the brief's re-review note.
write_prior() {
  local since="$1" run_dir="$2" src_repo="$3" head_oid="$4"
  local prior_head; prior_head=$(jq -r .headRefOid "$since/pr.json")
  {
    echo "# Prior review of this PR"
    echo
    echo "Prior run: $since — reviewed head $prior_head. Current head: $head_oid."
    echo
    if [[ -f "$since/final.md" ]]; then cat "$since/final.md"
    elif [[ -f "$since/venn.md" ]]; then
      echo "(The prior run left no final.md ledger; its Venn diagram follows. Dispositions are unknown.)"
      echo; cat "$since/venn.md"
    else echo "(The prior run left neither final.md nor venn.md.)"; fi
  } > "$run_dir/prior.md"
  if git -C "$src_repo" cat-file -e "${prior_head}^{commit}" 2>/dev/null; then
    # Limited to the PR's own files: a merge from the base between the two heads
    # would otherwise flood the delta with unrelated base-branch changes.
    local pr_files=() f
    while IFS= read -r f; do [[ -n "$f" ]] && pr_files+=("$f"); done < "$run_dir/changed_files.txt"
    git -C "$src_repo" diff "$prior_head" "$head_oid" -- ${pr_files[@]+"${pr_files[@]}"} \
      > "$run_dir/delta.patch" || true
  else
    info "prior head $prior_head is not in the local repo (force-push or gc) — no delta.patch"
  fi
  # Plain if/elif, not `$( [[ … ]] && … )`: an assignment whose last command
  # substitution fails aborts the script under set -e, and an empty delta is normal.
  local delta_clause=""
  if [[ -s "$run_dir/delta.patch" ]]; then
    delta_clause=", and the change since is \`$run_dir/delta.patch\`"
  elif [[ "$prior_head" == "$head_oid" ]]; then
    delta_clause=" — the head has not moved since"
  fi
  printf '%s\n' "> **This is a re-review.** A prior run reviewed head \`$prior_head\`; its findings,
> their dispositions and what was posted are in \`$run_dir/prior.md\`$delta_clause.
> Still review the whole PR. Read prior.md first: report every prior finding that is
> still present (same root cause, even if unchanged), and do not re-raise one that
> prior.md records as rejected, rebutted by the author, deferred by the author (a
> ticket, a follow-up), or declined by the user unless the code it rests on changed
> since — then say what changed."
}

# ── prepare ──────────────────────────────────────────────────────────────────
# Builds the shared snapshot both reviewers see: PR metadata, the full diff, and
# a detached worktree at the PR head so file reads land on the right revision.
cmd_prepare() {
  local pr="" task="" claude_model="opus" claude_effort="high"
  local codex_model="gpt-6.1-sol" codex_effort="high" timeout_s=2400
  local since="" context_repos=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --pr)            pr="$2"; shift 2 ;;
      --task)          task="$2"; shift 2 ;;
      --claude-model)  claude_model="$2"; shift 2 ;;
      --claude-effort) claude_effort="$2"; shift 2 ;;
      --codex-model)   codex_model="$2"; shift 2 ;;
      --codex-effort)  codex_effort="$2"; shift 2 ;;
      --timeout)       timeout_s="$2"; shift 2 ;;
      --since)         since="$2"; shift 2 ;;
      --context-repo)  [[ -d "$2" ]] || die "--context-repo: no such directory: $2"
                       context_repos+=("$(cd "$2" && pwd)"); shift 2 ;;
      *) die "unknown flag: $1" ;;
    esac
  done
  [[ -n "$pr" ]] || die "--pr is required (URL or number)"
  [[ -n "$task" ]] || task="Do a thorough review. Surface any issues or bugs as blocking or non-blocking."
  if [[ -n "$since" ]]; then
    [[ -f "$since/config.env" && -f "$since/pr.json" ]] || die "--since: $since is not a dual-review run dir"
  fi
  require_tools

  local src_repo; src_repo=$(git rev-parse --show-toplevel 2>/dev/null) \
    || die "not inside a git repository; cd to a checkout of the PR's repo first"

  local owner_repo
  if [[ "$pr" == http* ]]; then
    owner_repo=$(sed -E 's#https?://[^/]+/([^/]+/[^/]+)/pull/.*#\1#' <<<"$pr")
    pr=$(sed -E 's#.*/pull/([0-9]+).*#\1#' <<<"$pr")
  else
    owner_repo=$(gh repo view --json nameWithOwner -q .nameWithOwner) \
      || die "could not determine the repository; pass a full PR URL"
  fi

  info "fetching PR metadata…"
  local meta
  meta=$(gh pr view "$pr" --repo "$owner_repo" --json \
    number,title,url,author,baseRefName,baseRefOid,headRefName,headRefOid,body,additions,deletions,changedFiles,files,isCrossRepository)

  local num head_oid slug
  num=$(jq -r .number <<<"$meta")
  head_oid=$(jq -r .headRefOid <<<"$meta")
  slug="$(basename "$src_repo")-pr${num}-$(date +%Y%m%d-%H%M%S)"

  local run_dir="$RUNS_ROOT/$slug"
  local wt="$WORKTREE_ROOT/$(basename "$src_repo")/pr-${num}-review"
  mkdir -p "$run_dir"
  # A prepare that dies halfway leaves a run dir that looks like a run; config.env
  # is written last, so its absence marks the dir as a stub to remove.
  PREP_RUN_DIR="$run_dir"
  trap '[[ -n "${PREP_RUN_DIR:-}" && ! -f "$PREP_RUN_DIR/config.env" ]] && rm -rf "$PREP_RUN_DIR"; true' EXIT
  jq . <<<"$meta" > "$run_dir/pr.json"
  jq -r '.files[].path' <<<"$meta" > "$run_dir/changed_files.txt"

  info "fetching diff…"
  gh pr diff "$pr" --repo "$owner_repo" > "$run_dir/diff.patch"
  [[ -s "$run_dir/diff.patch" ]] || die "PR diff is empty — wrong PR, or no permission to read it"

  info "checking out PR head $head_oid into a worktree…"
  local fetch_err
  fetch_err=$(git -C "$src_repo" fetch -q origin "pull/${num}/head" 2>&1) || {
    local hint=""
    [[ "$fetch_err" == *refs/prefetch* ]] && hint=" — stale maintenance prefetch refs; delete them with: git -C $src_repo for-each-ref --format='%(refname)' refs/prefetch | xargs -n1 git -C $src_repo update-ref -d"
    die "could not fetch pull/${num}/head: ${fetch_err}${hint}"
  }

  # The diff must be against the PR's OWN base, not the default branch. On a
  # stacked PR those differ, and diffing against main would attribute the parent
  # branch's changes to this PR.
  local base_ref base_oid default_branch merge_base="" base_local=""
  base_ref=$(jq -r .baseRefName <<<"$meta")
  base_oid=$(jq -r .baseRefOid <<<"$meta")
  default_branch=$(gh repo view "$owner_repo" --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || echo "")
  if git -C "$src_repo" fetch -q origin "+refs/heads/${base_ref}:refs/dual-review/base-${num}" 2>/dev/null; then
    base_local="refs/dual-review/base-${num}"
    merge_base=$(git -C "$src_repo" merge-base "$base_local" "$head_oid" 2>/dev/null || echo "")
  fi
  if [[ -z "$merge_base" ]]; then
    merge_base="$base_oid"
    info "base branch '$base_ref' not fetchable (deleted, or on a fork) — using the API's base commit"
  fi

  git -C "$src_repo" worktree remove --force "$wt" 2>/dev/null || true
  # hooksPath is redirected because repos commonly run a dependency sync on
  # post-checkout; a read-only review worktree does not need one.
  git -C "$src_repo" -c core.hooksPath=/dev/null worktree add -q --detach "$wt" "$head_oid" \
    || die "could not create worktree at $head_oid"

  # Integrity check: what GitHub calls the diff and what merge-base..head says
  # must agree. When they don't, the snapshot is lying about the PR's scope.
  git -C "$src_repo" diff --name-only "$merge_base" "$head_oid" | sort > "$run_dir/.local_files"
  sort "$run_dir/changed_files.txt" > "$run_dir/.api_files"
  if ! diff -q "$run_dir/.local_files" "$run_dir/.api_files" >/dev/null; then
    diff "$run_dir/.api_files" "$run_dir/.local_files" > "$run_dir/diff_scope_mismatch.txt" || true
    info "WARNING: gh's file list and merge-base..head disagree — see diff_scope_mismatch.txt"
  fi
  rm -f "$run_dir/.local_files" "$run_dir/.api_files"

  info "fetching existing PR comments…"
  fetch_pr_comments "${owner_repo%%/*}" "${owner_repo##*/}" "$num" "$run_dir/comments.json"
  render_pr_comments "$run_dir/comments.json" > "$run_dir/comments.md"
  # A full dump runs to six figures of characters on an active PR; the live
  # subset is what an assessment round normally needs.
  jq '[.[] | select(.resolved == false and .outdated == false)]' "$run_dir/comments.json" \
    > "$run_dir/comments.live.json"
  render_pr_comments "$run_dir/comments.live.json" > "$run_dir/comments.live.md"
  local n_comments; n_comments=$(jq 'length' "$run_dir/comments.json")
  local n_live; n_live=$(jq '[.[] | select(.resolved == false and .outdated == false)] | length' "$run_dir/comments.json")

  info "looking for related PRs…"
  local related_note=""
  if find_related_prs "$owner_repo" "$num" "$src_repo" "$merge_base" "$head_oid" \
       "$run_dir/changed_files.txt" "$run_dir/related_prs.md"; then
    info "WARNING: commits from other PRs are in this diff — see related_prs.md (hidden stacking)"
    related_note="> **Commits from other pull requests are in this diff** — see
> \`$run_dir/related_prs.md\`. If such a PR is already merged, its work arrived here
> as pre-squash commits and is not this PR's change: do not report defects that
> belong to it, and say so when a finding sits only in that code."
  fi
  if grep -q '^- ' "$run_dir/related_prs.md" 2>/dev/null; then
    related_note+="${related_note:+$'\n\n'}\`$run_dir/related_prs.md\` lists related pull requests. Before suggesting
a follow-up, check whether one of them already does it."
  fi

  # Re-review: carry the prior run's outcome and the change since its head.
  local prior_note="" prior_head=""
  if [[ -n "$since" ]]; then
    prior_head=$(jq -r .headRefOid "$since/pr.json")
    prior_note=$(write_prior "$since" "$run_dir" "$src_repo" "$head_oid")
  fi

  local context_note
  if (( ${#context_repos[@]} )); then
    printf '%s\n' "${context_repos[@]}" > "$run_dir/context_repos.txt"
    context_note="Read-only checkouts of related repositories you may read: $(printf '`%s` ' "${context_repos[@]}")
They are NOT at a revision matched to this PR; say which revision you read when you cite one."
  else
    context_note="No other repository is available to you. A finding whose failure depends on
code outside this repository must say so in \`evidence\` and use \`confidence: low\`."
  fi

  cat > "$run_dir/config.env" <<EOF
RUN_DIR=$run_dir
SRC_REPO=$src_repo
WORKTREE=$wt
OWNER_REPO=$owner_repo
PR_NUM=$num
PR_URL=$(jq -r .url <<<"$meta")
BASE_REF=$base_ref
BASE_LOCAL_REF=$base_local
MERGE_BASE=$merge_base
DEFAULT_BRANCH=$default_branch
STACKED=$([[ -n "$default_branch" && "$base_ref" != "$default_branch" ]] && echo yes || echo no)
COMMENTS_TOTAL=$n_comments
COMMENTS_LIVE=$n_live
CLAUDE_MODEL=$claude_model
CLAUDE_EFFORT=$claude_effort
CODEX_MODEL=$codex_model
CODEX_EFFORT=$codex_effort
AGENT_TIMEOUT=$timeout_s
SKILL_VERSION=$MODULE_VERSION
PRIOR_RUN=$since
PRIOR_HEAD=$prior_head
EOF
  printf '%s' "$task" > "$run_dir/task.txt"

  # Round-1 briefs: byte-identical except the id prefix each reviewer must use.
  local brief; brief=$(cat "$SKILL_DIR/references/review-brief.md")
  mkdir -p "$run_dir/round1"
  local key val
  while IFS=$'\t' read -r key val; do
    brief=${brief//"{{$key}}"/$val}
  done < <(jq -r --arg rd "$run_dir" --arg mb "$merge_base" '
      ["PR_URL", .url], ["PR_TITLE", .title], ["PR_AUTHOR", .author.login],
      ["PR_BASE", .baseRefName], ["PR_BASE_OID", .baseRefOid],
      ["PR_HEAD", .headRefName], ["PR_HEAD_OID", .headRefOid],
      ["PR_CHANGED", (.changedFiles|tostring)],
      ["PR_ADDITIONS", (.additions|tostring)], ["PR_DELETIONS", (.deletions|tostring)],
      ["MERGE_BASE", $mb], ["RUN_DIR", $rd]
      | @tsv' <<<"$meta")

  local stacked_note
  if [[ -n "$default_branch" && "$base_ref" != "$default_branch" ]]; then
    stacked_note="> **This PR is stacked.** Its base is \`$base_ref\`, not the default
> branch \`$default_branch\`. Your diff is this PR's own changes only, computed
> against merge base \`$merge_base\`. Anything that arrived via the parent branch
> is not this PR's work: do not review it, and do not report a defect the parent
> introduced. If a defect here is only reachable because of how the parent branch
> behaves, say so explicitly in your evidence."
  else
    stacked_note="This PR targets the default branch \`$base_ref\`, and the diff is computed
against merge base \`$merge_base\`."
  fi
  brief=${brief//"{{STACKED_NOTE}}"/$stacked_note}
  brief=${brief//"{{RELATED_NOTE}}"/$related_note}
  brief=${brief//"{{PRIOR_NOTE}}"/$prior_note}
  brief=${brief//"{{CONTEXT_NOTE}}"/$context_note}
  brief=${brief//"{{TASK}}"/$task}
  printf '%s' "${brief//"{{ID_PREFIX}}"/CC-}" > "$run_dir/round1/claude.prompt.md"
  printf '%s' "${brief//"{{ID_PREFIX}}"/CX-}" > "$run_dir/round1/codex.prompt.md"

  info "base=$base_ref  merge-base=$merge_base  stacked=$([[ "$base_ref" != "$default_branch" ]] && echo yes || echo no)"
  info "existing comments: $n_comments total, $n_live unresolved and current"
  [[ -z "$since" ]] || info "re-review of $since (prior head $prior_head) — see prior.md"
  info "skill version: $MODULE_VERSION"
  echo "$run_dir"
}

# ── run ──────────────────────────────────────────────────────────────────────
# Dispatches the reviewers in parallel and blocks until both settle. Call this
# with run_in_background and poll `status`; a real review takes many minutes.
#
# A side with no prompt file is skipped (an empty docket), and --only re-runs one
# side while leaving the other's results alone. Any earlier attempt of a side
# being launched is moved to <round>/attempt-N/ first, so a failed try stays on
# record and nobody has to rename files or hand-write a .status to recover.
cmd_run() {
  local only=""
  local args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --only) only="$2"; shift 2 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  [[ -z "$only" || "$only" == claude || "$only" == codex ]] || die "--only takes claude or codex"
  local run_dir="${args[0]:?run_dir}" round="${args[1]:?round name}" schema="${args[2]:?schema name}"
  # shellcheck disable=SC1091
  source "$run_dir/config.env"
  local dir="$run_dir/$round"
  local schema_file="$SKILL_DIR/schemas/${schema}.json"
  [[ -f "$schema_file" ]] || die "no such schema: $schema_file"

  local sides=() who
  for who in claude codex; do
    [[ -z "$only" || "$only" == "$who" ]] || continue
    if [[ -f "$dir/$who.prompt.md" ]]; then sides+=("$who")
    elif [[ -n "$only" ]]; then die "--only $who: no $dir/$who.prompt.md"
    fi
  done
  (( ${#sides[@]} )) || die "no prompts in $dir (write claude.prompt.md and/or codex.prompt.md first)"

  # Later rounds are composed by hand from the brief templates, and an unfilled
  # placeholder is silent: the agent receives the literal {{DOCKET}} and answers
  # around it. Cheaper to refuse the launch than to debug the verdicts.
  # `|| true` is load-bearing: grep exits 1 when it finds nothing, and under
  # `set -euo pipefail` that would abort the run on the happy path.
  local unfilled
  unfilled=$(for who in "${sides[@]}"; do grep -oh '{{[A-Z_]*}}' "$dir/$who.prompt.md" 2>/dev/null; done | sort -u | tr '\n' ' ' || true)
  [[ -z "${unfilled// /}" ]] || die "unfilled placeholders in $dir prompts: $unfilled"

  # Both reviewers read untrusted PR content (diff, description, comments) from a
  # worktree whose .claude/ and .codex/ the PR author controls, so each runs on an
  # allow-list with no network, no inherited user config, and no MCP or skills.
  local codex_bin; codex_bin=$(resolve_codex)
  # --ignore-user-config drops user MCP servers and project trust entries (so the
  # PR's own .codex/ layers stay untrusted); --ignore-rules drops execpolicy rules
  # that could run commands outside the sandbox; apps traffic bypasses the sandbox.
  local codex_sandbox; codex_sandbox=$(codex_sandbox_mode)
  local codex_iso=(--sandbox "$codex_sandbox" --add-dir "$RUN_DIR"
    --ignore-user-config --ignore-rules
    -c approval_policy='"never"' -c features.apps=false
    -c web_search='"disabled"' -c shell_environment_policy.inherit='"core"')
  # --setting-sources "" keeps the PR's .claude/settings.json and the user's allow
  # rules out; --tools removes Skill/WebFetch/Agent outright; dontAsk denies any
  # Bash outside the read-only built-ins and this allow-list (curl, gh, rm…).
  local claude_iso=(--permission-mode dontAsk --setting-sources "" --strict-mcp-config
    --tools "Read,Grep,Glob,Bash"
    --allowedTools "Read,Grep,Glob,Bash(git diff:*),Bash(git show:*),Bash(git log:*),Bash(git blame:*)"
    --settings '{"permissions":{"blockReadsOutsideWorkingDirectories":true}}'
    --add-dir "$RUN_DIR")
  local context_dirs=()
  if [[ -f "$run_dir/context_repos.txt" ]]; then
    local d; while IFS= read -r d; do [[ -n "$d" ]] && context_dirs+=(--add-dir "$d"); done < "$run_dir/context_repos.txt"
  fi

  # Every check that can refuse the launch is above this line; only now move an
  # earlier attempt of the sides about to run out of the way.
  local f n
  for who in "${sides[@]}"; do
    local prev=0
    for f in "$dir/$who".*; do [[ -e "$f" && "$f" != *.prompt.md ]] && prev=1; done
    if [[ $prev == 1 ]]; then
      n=1; while [[ -e "$dir/attempt-$n/$who.exit" || -e "$dir/attempt-$n/$who.status" || -e "$dir/attempt-$n/$who.log" ]]; do n=$((n + 1)); done
      mkdir -p "$dir/attempt-$n"
      for f in "$dir/$who".*; do [[ "$f" == *.prompt.md ]] || mv "$f" "$dir/attempt-$n/"; done
      info "$who: earlier attempt moved to $dir/attempt-$n/"
    fi
  done
  # A side with no prompt that has never run is an empty docket, not a failure.
  for who in claude codex; do
    [[ -f "$dir/$who.prompt.md" || -f "$dir/$who.status" ]] || echo "skipped (no prompt — empty docket)" > "$dir/$who.status"
  done

  # `|| rc=$?` is load-bearing: this subshell inherits `set -e`, so a bare failing
  # launch would end it before the exit code is written, and every non-zero exit
  # (credits, auth, timeout's 124) would surface as "exit ?".
  local pids=()
  if [[ " ${sides[*]} " == *" claude "* ]]; then
    (
      cd "$WORKTREE" || exit 1
      rc=0
      run_with_timeout "$AGENT_TIMEOUT" claude -p "$(cat "$dir/claude.prompt.md")" \
        --model "$CLAUDE_MODEL" --effort "$CLAUDE_EFFORT" \
        --output-format json --json-schema "$(cat "$schema_file")" \
        "${claude_iso[@]}" ${context_dirs[@]+"${context_dirs[@]}"} \
        </dev/null >"$dir/claude.raw.json" 2>"$dir/claude.log" || rc=$?
      echo "$rc" > "$dir/claude.exit"
    ) &
    pids+=($!)
  fi
  if [[ " ${sides[*]} " == *" codex "* ]]; then
    (
      cd "$WORKTREE" || exit 1
      rc=0
      run_with_timeout "$AGENT_TIMEOUT" "$codex_bin" exec "$(cat "$dir/codex.prompt.md")" \
        --model "$CODEX_MODEL" -c model_reasoning_effort="$CODEX_EFFORT" \
        "${codex_iso[@]}" \
        --output-schema "$schema_file" \
        --output-last-message "$dir/codex.raw.json" \
        </dev/null >"$dir/codex.stdout" 2>"$dir/codex.log" || rc=$?
      echo "$rc" > "$dir/codex.exit"
    ) &
    pids+=($!)
  fi
  local pid; for pid in "${pids[@]}"; do wait "$pid" || true; done

  # claude wraps the answer in a result envelope; codex writes the bare message.
  [[ " ${sides[*]} " != *" claude "* ]] || jq -e '.structured_output // (.result | fromjson)' "$dir/claude.raw.json" \
     > "$dir/claude.json" 2>/dev/null || true
  [[ " ${sides[*]} " != *" codex "* ]] || jq -e . "$dir/codex.raw.json" > "$dir/codex.json" 2>/dev/null || true

  for who in "${sides[@]}"; do
    local valid=0
    [[ -s "$dir/$who.json" ]] && jq -e 'type=="object"' "$dir/$who.json" >/dev/null 2>&1 && valid=1
    if [[ $who == claude ]]; then
      if [[ $valid == 1 ]]; then echo "ok" > "$dir/claude.status"
      else echo "failed (exit $(cat "$dir/claude.exit" 2>/dev/null || echo '?'); see claude.log)" > "$dir/claude.status"; fi
      continue
    fi
    # A reviewer that never ran a command in the worktree never read the code, and
    # codex answers anyway when its sandbox cannot start or its account is dead.
    # Gate on evidence of reads rather than on one known error string.
    # The cause is looked for only once the round has failed: codex.log carries
    # command output, so a PR whose code mentions "401" or "bubblewrap" would
    # otherwise void a good review.
    local execs cause
    execs=$(codex_worktree_execs "$dir/codex.log" "$RUN_DIR")
    if [[ $valid == 1 && $execs -gt 0 ]]; then
      local items floor
      items=$(jq '(.findings // .verdicts // .assessments // []) | length' "$dir/codex.json")
      floor=$(( (items + 2) / 3 ))
      if [[ $schema != findings && $execs -lt $floor ]]; then
        echo "ok (low evidence: $execs worktree command(s) for $items item(s) — spot-check its citations)" > "$dir/codex.status"
      else echo "ok" > "$dir/codex.status"; fi
    else
      rm -f "$dir/codex.json"
      cause=$(codex_failure_cause "$dir")
      [[ -n "$cause" ]] || if [[ $execs -eq 0 && -f "$dir/codex.log" ]]; then
        cause="codex ran no successful shell command in the PR worktree — it read no code, so its findings are unfounded"
      else cause="no valid JSON answer; see codex.log"; fi
      echo "failed (exit $(cat "$dir/codex.exit" 2>/dev/null || echo '?')): $cause" > "$dir/codex.status"
    fi
  done
  local rc=0
  for who in claude codex; do
    case "$(cat "$dir/$who.status" 2>/dev/null)" in ok*|skipped*) ;; *) rc=1 ;; esac
  done
  cmd_status "$run_dir" "$round"
  return $rc
}

cmd_status() {
  local run_dir="${1:?run_dir}" round="${2:?round}"
  local dir="$run_dir/$round"
  for who in claude codex; do
    if [[ -f "$dir/$who.status" ]]; then
      local n; n=$(jq -r '(.findings // .verdicts // .assessments // []) | length' "$dir/$who.json" 2>/dev/null || echo 0)
      echo "$who: $(cat "$dir/$who.status") — $n item(s) — $dir/$who.json"
    else
      echo "$who: running"
    fi
  done
}

# Lines an inline review comment can anchor to: the head-side ranges of every
# hunk in diff.patch. GitHub rejects a whole review (422) when one of its
# comments points outside them, so Step 8 checks each anchor before posting.
# With <path> <line>, exits 0 when that line is anchorable and 1 when it is not.
cmd_anchors() {
  local run_dir="${1:?run_dir}" want_path="${2:-}" want_line="${3:-}"
  local ranges
  ranges=$(awk '
    /^\+\+\+ / { path = ($2 == "/dev/null") ? "" : substr($2, 3); next }
    /^@@ / {
      split($3, h, ","); start = substr(h[1], 2) + 0; len = (h[2] == "") ? 1 : h[2] + 0
      if (path != "" && len > 0) print path "\t" start "\t" start + len - 1
    }' "$run_dir/diff.patch")
  if [[ -z "$want_path" ]]; then
    awk -F'\t' '{ print $1 ":" $2 "-" $3 }' <<<"$ranges"; return 0
  fi
  [[ "$want_line" =~ ^[0-9]+$ ]] || die "anchors: <line> must be a number"
  awk -F'\t' -v p="$want_path" -v l="$want_line" \
    '$1 == p && l >= $2 && l <= $3 { found = 1 } END { exit found ? 0 : 1 }' <<<"$ranges"
}

cmd_cleanup() {
  local run_dir="${1:?run_dir}"
  # shellcheck disable=SC1091
  source "$run_dir/config.env"
  git -C "$SRC_REPO" worktree remove --force "$WORKTREE" 2>/dev/null \
    && echo "removed worktree $WORKTREE" || echo "worktree already gone"
  if [[ -n "${BASE_LOCAL_REF:-}" ]]; then
    git -C "$SRC_REPO" update-ref -d "$BASE_LOCAL_REF" 2>/dev/null || true
  fi
  echo "run artifacts kept at $run_dir"
}

case "${1:-}" in
  preflight) shift; cmd_preflight "$@" ;;
  prepare)   shift; cmd_prepare "$@" ;;
  run)       shift; cmd_run "$@" ;;
  status)    shift; cmd_status "$@" ;;
  anchors)   shift; cmd_anchors "$@" ;;
  cleanup)   shift; cmd_cleanup "$@" ;;
  *) cat >&2 <<'USAGE'
usage: dual_review.sh <command>
  preflight
  prepare --pr <url|number> --task <text>
          [--claude-model opus] [--claude-effort high]
          [--codex-model gpt-6.1-sol] [--codex-effort high] [--timeout 2400]
          [--since <prior run_dir>] [--context-repo <path>]...
  run     [--only claude|codex] <run_dir> <round> <findings|verdicts|comment-verdicts>
  status  <run_dir> <round>
  anchors <run_dir> [<path> <line>]
  cleanup <run_dir>
USAGE
     exit 2 ;;
esac
