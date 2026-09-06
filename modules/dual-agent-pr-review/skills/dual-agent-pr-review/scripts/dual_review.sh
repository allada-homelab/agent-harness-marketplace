#!/usr/bin/env bash
# Orchestrates two independent CLI code reviewers (Claude Code + Codex) over one
# PR snapshot. Deterministic plumbing only — all judgment (pairing findings,
# deciding consensus) belongs to the calling agent.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS_ROOT="${DUAL_REVIEW_RUNS:-$HOME/.claude/dual-review/runs}"
WORKTREE_ROOT="${DUAL_REVIEW_WORKTREES:-$HOME/.git-worktree}"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "  $*" >&2; }

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

# codex sandboxes tool calls with bubblewrap, which needs unprivileged user
# namespaces. Inside a devcontainer those are usually blocked, and codex then
# fails EVERY shell command while still answering — i.e. it reviews from
# imagination. Detect that up front and run unsandboxed instead (the container
# is already the sandbox), rather than shipping a fabricated review.
# Picks codex's sandbox backend. Its default, bubblewrap, needs an unprivileged
# user namespace; container seccomp policies commonly deny that, and codex then
# fails every shell call while still answering — a review with no file reads
# behind it. Landlock enforces in-kernel on the calling process, needs no
# namespace, and keeps the read-only sandbox intact, so it is the fallback rather
# than turning the sandbox off.
probe_codex_sandbox() {
  if unshare -Ur true >/dev/null 2>&1; then echo "bwrap"; else echo "landlock"; fi
}

require_tools() {
  command -v claude >/dev/null 2>&1 || die "claude CLI not found on PATH."
  command -v gh  >/dev/null 2>&1 || die "gh CLI not found on PATH."
  command -v jq  >/dev/null 2>&1 || die "jq not found on PATH."
  gh auth status >/dev/null 2>&1 || die "gh is not authenticated. Run: gh auth login"
  resolve_codex >/dev/null
}

# ── preflight ────────────────────────────────────────────────────────────────
cmd_preflight() {
  require_tools
  echo "claude : $(command -v claude) ($(claude --version 2>/dev/null | head -1))"
  echo "codex  : $(resolve_codex) ($("$(resolve_codex)" --version 2>/dev/null | head -1))"
  echo "gh     : authenticated"
  echo "runs   : $RUNS_ROOT"
  case "$(probe_codex_sandbox)" in
    bwrap)    echo "codex sandbox : bubblewrap (user namespaces available)" ;;
    landlock) echo "codex sandbox : landlock (no user namespaces here; --enable use_legacy_landlock)" ;;
  esac
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
            comments(first:50){ nodes{ author{login} body url createdAt diffHunk } } } }
          reviews(first:100){ nodes{ author{login} body url createdAt state } }
          comments(first:100){ nodes{ author{login} body url createdAt } } } } }' 2>/dev/null) \
    || { echo '[]' > "$out"; return; }

  jq '
    def person: (.author.login // "unknown");
    [ ( .data.repository.pullRequest.reviewThreads.nodes[] | . as $t
        | $t.comments.nodes[0] | select(. != null)
        | { kind: "inline", author: person, path: $t.path,
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
      + "\n\(.url)\n\n\(.body)\n"
      + (if (.diff_hunk | length) > 0 then "\nCommented on this hunk:\n```diff\n\(.diff_hunk)\n```\n" else "" end)
      + (if (.replies | length) > 0 then "\nReplies:\n" + ([.replies[] | "- **\(.author)**: \(.body)"] | join("\n")) + "\n" else "" end)
      + "\n---\n" )
    end' "$1"
}

# ── prepare ──────────────────────────────────────────────────────────────────
# Builds the shared snapshot both reviewers see: PR metadata, the full diff, and
# a detached worktree at the PR head so file reads land on the right revision.
cmd_prepare() {
  local pr="" task="" claude_model="opus" claude_effort="high"
  local codex_model="gpt-5.6-sol" codex_effort="high" timeout_s=2400
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --pr)            pr="$2"; shift 2 ;;
      --task)          task="$2"; shift 2 ;;
      --claude-model)  claude_model="$2"; shift 2 ;;
      --claude-effort) claude_effort="$2"; shift 2 ;;
      --codex-model)   codex_model="$2"; shift 2 ;;
      --codex-effort)  codex_effort="$2"; shift 2 ;;
      --timeout)       timeout_s="$2"; shift 2 ;;
      *) die "unknown flag: $1" ;;
    esac
  done
  [[ -n "$pr" ]] || die "--pr is required (URL or number)"
  [[ -n "$task" ]] || task="Do a thorough review. Surface any issues or bugs as blocking or non-blocking."
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
  jq . <<<"$meta" > "$run_dir/pr.json"
  jq -r '.files[].path' <<<"$meta" > "$run_dir/changed_files.txt"

  info "fetching diff…"
  gh pr diff "$pr" --repo "$owner_repo" > "$run_dir/diff.patch"
  [[ -s "$run_dir/diff.patch" ]] || die "PR diff is empty — wrong PR, or no permission to read it"

  info "checking out PR head $head_oid into a worktree…"
  git -C "$src_repo" fetch -q origin "pull/${num}/head" || die "could not fetch pull/${num}/head"

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
  brief=${brief//"{{TASK}}"/$task}
  printf '%s' "${brief//"{{ID_PREFIX}}"/CC-}" > "$run_dir/round1/claude.prompt.md"
  printf '%s' "${brief//"{{ID_PREFIX}}"/CX-}" > "$run_dir/round1/codex.prompt.md"

  info "base=$base_ref  merge-base=$merge_base  stacked=$([[ "$base_ref" != "$default_branch" ]] && echo yes || echo no)"
  info "existing comments: $n_comments total, $n_live unresolved and current"
  echo "$run_dir"
}

# ── run ──────────────────────────────────────────────────────────────────────
# Dispatches both reviewers in parallel and blocks until both settle. Call this
# with run_in_background and poll `status`; a real review takes many minutes.
cmd_run() {
  local run_dir="${1:?run_dir}" round="${2:?round name}" schema="${3:?schema name}"
  # shellcheck disable=SC1091
  source "$run_dir/config.env"
  local dir="$run_dir/$round"
  local schema_file="$SKILL_DIR/schemas/${schema}.json"
  [[ -f "$schema_file" ]] || die "no such schema: $schema_file"
  [[ -f "$dir/claude.prompt.md" && -f "$dir/codex.prompt.md" ]] \
    || die "missing prompts in $dir (write claude.prompt.md and codex.prompt.md first)"

  # Later rounds are composed by hand from the brief templates, and an unfilled
  # placeholder is silent: the agent receives the literal {{DOCKET}} and answers
  # around it. Cheaper to refuse the launch than to debug the verdicts.
  # `|| true` is load-bearing: grep exits 1 when it finds nothing, and under
  # `set -euo pipefail` that would abort the run on the happy path.
  local unfilled
  unfilled=$(grep -oh '{{[A-Z_]*}}' "$dir/claude.prompt.md" "$dir/codex.prompt.md" 2>/dev/null | sort -u | tr '\n' ' ' || true)
  [[ -z "${unfilled// /}" ]] || die "unfilled placeholders in $dir prompts: $unfilled"

  local codex_bin; codex_bin=$(resolve_codex)
  local codex_iso=(--sandbox read-only --add-dir "$RUN_DIR")
  [[ "$(probe_codex_sandbox)" == "landlock" ]] && codex_iso+=(--enable use_legacy_landlock)
  rm -f "$dir"/*.status

  (
    cd "$WORKTREE" || exit 1
    timeout "$AGENT_TIMEOUT" claude -p "$(cat "$dir/claude.prompt.md")" \
      --model "$CLAUDE_MODEL" --effort "$CLAUDE_EFFORT" \
      --output-format json --json-schema "$(cat "$schema_file")" \
      --permission-mode bypassPermissions \
      --disallowed-tools "Edit,Write,NotebookEdit,Bash(git commit:*),Bash(git push:*),Bash(gh pr comment:*),Bash(gh pr review:*),Bash(gh pr merge:*),Bash(gh pr close:*)" \
      --add-dir "$RUN_DIR" \
      </dev/null >"$dir/claude.raw.json" 2>"$dir/claude.log"
    echo $? > "$dir/claude.exit"
  ) &
  local claude_pid=$!

  (
    cd "$WORKTREE" || exit 1
    timeout "$AGENT_TIMEOUT" "$codex_bin" exec "$(cat "$dir/codex.prompt.md")" \
      --model "$CODEX_MODEL" -c model_reasoning_effort="$CODEX_EFFORT" \
      "${codex_iso[@]}" \
      --output-schema "$schema_file" \
      --output-last-message "$dir/codex.raw.json" \
      </dev/null >"$dir/codex.stdout" 2>"$dir/codex.log"
    echo $? > "$dir/codex.exit"
  ) &
  local codex_pid=$!

  wait "$claude_pid" || true
  wait "$codex_pid" || true

  # claude wraps the answer in a result envelope; codex writes the bare message.
  jq -e '.structured_output // (.result | fromjson)' "$dir/claude.raw.json" \
     > "$dir/claude.json" 2>/dev/null || true
  jq -e . "$dir/codex.raw.json" > "$dir/codex.json" 2>/dev/null || true

  local rc=0
  # A reviewer that never ran a command never read the code, and codex answers
  # anyway when its sandbox cannot start. Gate on evidence of a successful exec
  # rather than on one known error string, so any future cause is caught too.
  if [[ -f "$dir/codex.log" ]] && ! grep -q "succeeded in" "$dir/codex.log"; then
    echo "failed (codex ran no successful shell command — it read no files, so its findings are unfounded; see codex.log)" \
      > "$dir/codex.status"
    rm -f "$dir/codex.json"
  fi
  for who in claude codex; do
    if [[ -f "$dir/$who.status" ]]; then
      rc=1
    elif [[ -s "$dir/$who.json" ]] && jq -e 'type=="object"' "$dir/$who.json" >/dev/null 2>&1; then
      echo "ok" > "$dir/$who.status"
    else
      echo "failed (exit $(cat "$dir/$who.exit" 2>/dev/null || echo '?'); see $who.log)" > "$dir/$who.status"
      rc=1
    fi
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
  cleanup)   shift; cmd_cleanup "$@" ;;
  *) cat >&2 <<'USAGE'
usage: dual_review.sh <command>
  preflight
  prepare --pr <url|number> --task <text>
          [--claude-model opus] [--claude-effort high]
          [--codex-model gpt-5.6-sol] [--codex-effort high] [--timeout 2400]
  run     <run_dir> <round> <findings|verdicts|comment-verdicts>
  status  <run_dir> <round>
  cleanup <run_dir>
USAGE
     exit 2 ;;
esac
