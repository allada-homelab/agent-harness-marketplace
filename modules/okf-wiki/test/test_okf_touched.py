import time

from okf_testlib import GOOD_BODY, GOOD_META, concept, git, okf, run


def fresh(repo):
    return okf.freshness(repo, okf.load(repo / ".wiki"))


def stamped(repo, cid="x", body=GOOD_BODY):
    concept(repo, cid, body=body)
    r = run(repo, "stamp", cid, "--by", "okf-wiki/haiku", "--verified")
    assert r.returncode == 0, r.stdout
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"wiki {cid}")


def commit_app(repo, text, msg="change"):
    (repo / "src" / "app.py").write_text(text)
    git(repo, "commit", "-qam", msg)


def at_head(repo, body):
    """A concept verified at HEAD without going through stamp (which refuses failing anchors)."""
    meta = GOOD_META + f"verified:\n  - {{by: x/y, at: 2026-01-01T00:00:00Z, commit: {okf.head_commit(repo)}}}\n"
    return meta, body


def test_a_touch_that_leaves_the_anchored_line_alone_is_touched_not_stale(repo):
    stamped(repo)
    commit_app(repo, "def resolve_peers():\n    return 2\n")
    state, detail = fresh(repo)["x"]
    assert state == "TOUCHED" and detail.startswith("src/app.py changed in ") and detail.endswith("; anchors hold")
    r = run(repo, "fresh")
    assert r.stdout.splitlines()[0].startswith("TOUCHED x (src/app.py changed in ")
    assert r.stdout.splitlines()[-1] == "okf: fresh ok 0 fresh, 1 touched, 0 stale, 0 unanchored, 0 unverified"
    text = run(repo, "digest").stdout
    assert "- [gotcha] x — " in text and "⚠" not in text.split("\n", 2)[2]


def test_an_anchor_that_now_fails_is_stale(repo):
    stamped(repo)
    commit_app(repo, "def renamed():\n    return 2\n")
    state, detail = fresh(repo)["x"]
    assert state == "STALE" and detail.startswith("src/app.py changed in ")
    assert detail.endswith(": `resolve_peers` not found in src/app.py")


def test_a_count_anchor_judges_the_lines_its_regex_matches(repo):
    stamped(repo, body="\n## Verify\n\n- `src/app.py` :: /^def / => 1\n")
    commit_app(repo, "def resolve_peers():\n    return 2\n")
    assert fresh(repo)["x"][0] == "TOUCHED"
    commit_app(repo, "def resolve_peers(strict=True):\n    return 2\n")
    state, detail = fresh(repo)["x"]
    assert state == "STALE" and "matched line 'def resolve_peers(strict=True):'" in detail


def test_an_uncommitted_touch_of_an_unanchored_line_is_touched(repo):
    stamped(repo)
    time.sleep(1.1)  # verification is stamped to the second; this edit comes after it
    (repo / "src" / "app.py").write_text("def resolve_peers():\n    return 3\n")
    assert fresh(repo)["x"] == ("TOUCHED", "uncommitted change to src/app.py; anchors hold")


def test_a_missing_or_oversized_anchor_file_is_stale_even_untouched(repo):
    (repo / "big.txt").write_text("needle\n" + "x" * 2_000_001)
    git(repo, "add", "big.txt")
    git(repo, "commit", "-qm", "big")
    concept(repo, "missing", *at_head(repo, "\n## Verify\n\n- `src/nope.py` :: `x`\n"))
    concept(repo, "big", *at_head(repo, "\n## Verify\n\n- `big.txt` :: `needle`\n"))
    res = fresh(repo)
    assert res["missing"] == ("STALE", "src/nope.py does not exist")
    assert res["big"] == ("STALE", "big.txt is too large to check")


def test_a_sibling_commit_carrying_the_verified_change_is_touched(repo):
    # The work lands twice: once on a branch, once (cherry-picked) on main where the concept
    # is verified. Merging the branch brings a commit that is not a descendant of the verified
    # commit and touches the anchor file, but the anchored line is already in the verified copy.
    git(repo, "checkout", "-qb", "work")
    commit_app(repo, "def resolve_peers(strict=True):\n    return 1\n", "work")
    work = okf.head_commit(repo)
    git(repo, "checkout", "-q", "main")
    git(repo, "cherry-pick", "-x", work)  # -x: a distinct sha even within the same second
    assert okf.head_commit(repo) != work
    stamped(repo, body=GOOD_BODY.replace("`resolve_peers`", "`def resolve_peers(strict=True):`"))
    git(repo, "merge", "-q", "--no-ff", "-m", "merge work", "work")
    state, detail = fresh(repo)["x"]
    assert state == "TOUCHED" and detail.startswith(f"src/app.py changed in {work[:7]}")


def split_capture(repo):
    """The capture flow: stamp while the work is uncommitted, commit the work, then the wiki."""
    (repo / "src" / "app.py").write_text("def resolve_peers(strict=True):\n    return 1\n")
    concept(repo, "x")
    assert run(repo, "stamp", "x", "--by", "okf-wiki/haiku", "--verified").returncode == 0
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-qm", "work")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")


def test_a_concept_stamped_before_its_work_commit_and_committed_after_it_is_not_stale(repo):
    split_capture(repo)
    state, detail = fresh(repo)["x"]
    assert state == "TOUCHED" and detail.endswith("; anchors hold")


def test_changing_the_anchored_line_after_the_concept_commit_is_still_stale(repo):
    split_capture(repo)
    commit_app(repo, "def resolve_peers(strict=False):\n    return 1\n", "later")
    state, detail = fresh(repo)["x"]
    assert state == "STALE" and "matched line 'def resolve_peers(strict=False):'" in detail


def test_a_later_concept_only_commit_does_not_rebaseline_drifted_code(repo):
    stamped(repo)                                              # stamp, then commit the concept
    commit_app(repo, "def resolve_peers(strict=False):\n    return 1\n", "drift")
    p = repo / ".wiki" / "x.md"
    p.write_text(p.read_text().replace("tags: [pnpm, deps]", "tags: [pnpm, peers]"))
    git(repo, "commit", "-qam", "retag")                       # concept-only, after the drift
    state, detail = fresh(repo)["x"]
    assert state == "STALE" and "matched line 'def resolve_peers(strict=False):'" in detail
