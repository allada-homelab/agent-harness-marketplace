import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# analyze.py reads CLAUDE_CONFIG_DIR at import time to locate the hooks it
# optionally replays; point it at the stand-in fixtures so the hooks-replay
# tests run in CI without the author's private hooks installed.
os.environ["CLAUDE_CONFIG_DIR"] = str(Path(__file__).resolve().parent / "fixtures")

sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parent.parent
        / "skills/claude-transcript-analyze"
    ),
)
import analyze as az

assert az.HOOKS_AVAILABLE, "test fixture hooks failed to load"


def U(text):
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def UR():
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": []}]},
    }


def A(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def T(t):
    return {"type": "text", "text": t}


def TU(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


def US(text):
    # user entry whose message.content is a bare STRING — the shape Claude Code
    # uses to inject Stop-hook feedback back into the conversation.
    return {"type": "user", "message": {"content": text}}


def _seed(root, entries):
    src = root / "host" / "projects" / "-tmp-x"
    src.mkdir(parents=True)
    (src / "s1.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _mksession(entries):
    # In-memory session for lens tests: lens_hooks_replay slices session["entries"]
    # by the turn's line range into its own tempfile, so no on-disk file is needed.
    return {
        "session_id": "s1",
        "source": "host",
        "project": "-tmp-x",
        "path": Path("/dev/null"),
        "entries": entries,
    }


def test_split_turns_segments_on_real_user_text():
    entries = [
        U("do a thing"),
        A(TU("Bash", command="ls")),
        UR(),
        A(T("done")),
        U("next"),
        A(T("hi")),
    ]
    turns = az.split_turns(entries)
    assert len(turns) == 2
    assert turns[0]["tool_uses"][0]["name"] == "Bash"
    assert turns[0]["assistant_texts"] == ["done"]
    assert turns[1]["tool_uses"] == []


def test_tool_result_user_entry_does_not_start_turn():
    entries = [U("go"), A(TU("Bash", command="true")), UR(), A(T("ok"))]
    assert len(az.split_turns(entries)) == 1


def test_index_and_flags_roundtrip(tmp_path):
    src = tmp_path / "host" / "projects" / "-tmp-x"
    src.mkdir(parents=True)
    lines = [
        json.dumps(e)
        for e in [U("edit it"), A(TU("Edit", file_path="/x")), UR(), A(T("done ✅"))]
    ]
    (src / "s1.jsonl").write_text("\n".join(lines) + "\n")
    out = tmp_path / "analysis"
    az.run_index(tmp_path, out)
    rows = [json.loads(ln) for ln in (out / "index.jsonl").read_text().splitlines()]
    assert rows[0]["edited"] is True and rows[0]["tools"] == {"Edit": 1}
    assert rows[0]["line_start"] == 1  # 1-based pointer into source jsonl


def test_excerpt_is_bounded(tmp_path):
    # a turn with a 10k-char assistant message must come back truncated to <= 2000 chars
    src = tmp_path / "host" / "projects" / "-tmp-x"
    src.mkdir(parents=True)
    big = "y" * 10_000
    (src / "s1.jsonl").write_text(
        "\n".join(json.dumps(e) for e in [U("q"), A(T(big))]) + "\n"
    )
    out = tmp_path / "analysis"
    az.run_index(tmp_path, out)
    text = az.render_excerpt(
        tmp_path / "host/projects/-tmp-x/s1.jsonl", 1, 2, context=2
    )
    assert len(text) < 5000 and "…[truncated]" in text


def test_hook_feedback_flags_injected_stop_block_not_lookalike(tmp_path):
    # Synthetic reconstruction of the SHAPE only (no real transcript text):
    # a reflect-on-done Stop block surfaces as a bare-string user entry prefixed
    # "Stop hook feedback:" that carries the block marker. A casual mention of a
    # "stop hook" without that prefix/marker must NOT be flagged.
    feedback = (
        "Stop hook feedback:\n[~/.claude/hooks/reflect-on-done.py]: "
        "Work-closing turn detected: the closing message has no status line."
    )
    _seed(
        tmp_path,
        [
            U("wrap up the work"),
            A(T("all set")),
            US(feedback),  # starts the turn following the Stop
            US("remind me to configure the stop hook later"),  # look-alike
        ],
    )
    az.run_index(tmp_path, tmp_path / "analysis")
    rows = [
        json.loads(ln)
        for ln in (tmp_path / "analysis" / "index.jsonl").read_text().splitlines()
    ]
    assert rows[0]["hook_blocks"] == []  # the work turn itself
    assert rows[1]["hook_blocks"] == ["reflect-on-done"]  # injected feedback turn
    assert rows[2]["hook_blocks"] == []  # casual mention, not a real block


def test_worktree_guard_blocks_repo_output_allows_plain(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed(repo, [U("hi")])
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    with pytest.raises(SystemExit):
        az.run_index(repo, repo / "analysis")

    plain = tmp_path / "plain"
    plain.mkdir()
    _seed(plain, [U("hi")])
    az.run_index(plain, plain / "analysis")  # must not raise


def test_verify_claims_would_fire_matches_hook_behavior():
    # claim + zero tools -> flagged; claim + any tool -> claim_with_tools instead
    t_fab = [U("fix it"), A(T("I ran the tests and they pass."))]
    t_ok = [
        U("fix it"),
        A(TU("Bash", command="pytest")),
        UR(),
        A(T("I ran the tests and they pass.")),
    ]
    flags_fab = az.lens_hooks_replay(_mksession(t_fab), az.split_turns(t_fab)[0])
    flags_ok = az.lens_claude_md(_mksession(t_ok), az.split_turns(t_ok)[0])
    assert any(f["rule"] == "hooks.verify_claims_would_fire" for f in flags_fab)
    assert any(f["rule"] == "claude_md.claim_with_tools" for f in flags_ok)


def test_reflect_would_fire_on_commit_without_status_icon():
    t = [
        U("ship it"),
        A(TU("Bash", command="git commit -m x")),
        UR(),
        A(T("Committed.")),
    ]
    flags = az.lens_hooks_replay(_mksession(t), az.split_turns(t)[0])
    assert any(f["rule"] == "hooks.reflect_would_fire" for f in flags)


def test_interrupted_turn_emits_no_would_fire():
    # Same turn as the test above, but the user cut it off: no Stop happened, so
    # replaying the hook over it would count a block that could not have landed.
    t = [
        U("ship it"),
        A(TU("Bash", command="git commit -m x")),
        UR(),
        A(T("Committed.")),
        U("[Request interrupted by user]"),
    ]
    flags = az.lens_hooks_replay(_mksession(t), az.split_turns(t)[0])
    assert not any(f["rule"].endswith("_would_fire") for f in flags)


def test_recorded_fire_survives_an_interrupt():
    t = [
        US(
            "Stop hook feedback:\n[~/.claude/hooks/reflect-on-done.py]: "
            "Work-closing turn detected"
        ),
        A(T("Committed.")),
        U("[Request interrupted by user]"),
    ]
    flags = az.lens_hooks_replay(_mksession(t), az.split_turns(t)[0])
    assert any(f["rule"] == "hooks.reflect_fired" for f in flags)


def test_hook_injection_turn_excluded_from_report_denominator(tmp_path):
    # The injection opens a turn of its own (segmentation must keep mirroring the
    # hook), but it is enforcement noise, not work — so rates divide by real turns.
    _seed(
        tmp_path,
        [
            U("do it"),
            A(T("Committed.")),
            US(
                "Stop hook feedback:\n[~/.claude/hooks/reflect-on-done.py]: "
                "Work-closing turn detected"
            ),
            A(T("✅ Done")),
        ],
    )
    out = tmp_path / "analysis"
    rows = az.run_index(tmp_path, out)
    assert [r["hook_pseudo_turn"] for r in rows] == [False, True]
    assert "2 (1 real, 1 Stop-hook pseudo-turns)" in (out / "report.md").read_text()


def test_blanket_git_add_and_force_push():
    t = [U("go"), A(TU("Bash", command="git add -A && git push --force origin main"))]
    flags = az.lens_claude_md(_mksession(t), az.split_turns(t)[0])
    rules = {f["rule"] for f in flags}
    assert {"claude_md.blanket_git_add", "claude_md.force_push"} <= rules


def test_force_with_lease_not_flagged():
    t = [U("go"), A(TU("Bash", command="git push --force-with-lease origin main"))]
    assert not any(
        f["rule"] == "claude_md.force_push"
        for f in az.lens_claude_md(_mksession(t), az.split_turns(t)[0])
    )


# ── 2026-08-10 audit regressions ────────────────────────────────────────────


def test_excerpt_marks_the_stop_block_boundary(tmp_path):
    # hooks.*_fired anchors to the INJECTION turn, so the excerpt necessarily
    # contains the assistant's post-block correction — which carries a status line
    # only because the hook demanded one. Labelers read that as proof the hook
    # misfired (reflect_fired scored 95% FP against a true 40%). The excerpt must
    # mark the boundary structurally so the two turns can't be confused.
    feedback = (
        "Stop hook feedback:\n[~/.claude/hooks/reflect-on-done.py]: "
        "Work-closing turn detected (commit / completion claim) but no status-line close."
    )
    src = tmp_path / "host" / "projects" / "-tmp-x"
    src.mkdir(parents=True)
    entries = [
        U("wrap it up"),
        A(T("Committed and pushed.")),  # the BLOCKED turn — no status icon
        US(feedback),
        A(T("✅ Done — committed · nothing needed from you.")),  # the CORRECTION
    ]
    (src / "s1.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    text = az.render_excerpt(src / "s1.jsonl", 1, len(entries), context=2)

    assert az.BLOCK_BOUNDARY_BANNER in text
    # the banner must sit between the blocked turn and the correction
    before, after = text.split(az.BLOCK_BOUNDARY_BANNER, 1)
    assert "Committed and pushed." in before
    assert "✅ Done" in after and "✅ Done" not in before
    # emitted once even if more Stop-block text follows
    assert text.count(az.BLOCK_BOUNDARY_BANNER) == 1


def test_excerpt_without_a_stop_block_has_no_banner(tmp_path):
    src = tmp_path / "host" / "projects" / "-tmp-x"
    src.mkdir(parents=True)
    (src / "s1.jsonl").write_text(
        "\n".join(json.dumps(e) for e in [U("q"), A(T("an ordinary answer"))]) + "\n"
    )
    text = az.render_excerpt(src / "s1.jsonl", 1, 2, context=2)
    assert az.BLOCK_BOUNDARY_BANNER not in text


def test_index_drops_a_stale_excerpt_cache(tmp_path):
    # An excerpt cache belongs to the index it was built from; leaving it beside a
    # rebuilt index is how the audit ended up labeling Jul-23 excerpts against an
    # Aug-10 index (and finding none for newer flags).
    _seed(tmp_path, [U("q"), A(T("an answer"))])
    out = tmp_path / "analysis"
    stale = out / "excerpts"
    stale.mkdir(parents=True)
    (stale / "old.txt").write_text("excerpt from a previous index")

    az.run_index(tmp_path, out)

    assert not stale.exists()
    assert (out / "index.jsonl").exists()  # the rebuild still happened
