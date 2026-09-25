import time

from okf_testlib import GOOD_BODY, concept, git, okf, run


def stamped(repo, cid="x", body=GOOD_BODY):
    concept(repo, cid, body=body)
    r = run(repo, "stamp", cid, "--by", "okf-wiki/haiku", "--verified")
    assert r.returncode == 0, r.stdout


def fresh(repo):
    return okf.freshness(repo, okf.load(repo / ".wiki"))


def commit_app(repo, text, msg="change"):
    (repo / "src" / "app.py").write_text(text)
    git(repo, "commit", "-qam", msg)


def test_fresh_after_stamp(repo):
    stamped(repo)
    assert fresh(repo)["x"] == ("FRESH", "")


def test_commit_touching_an_anchor_file_makes_it_stale(repo):
    stamped(repo)
    commit_app(repo, "def resolve_peers():\n    return 2\n")
    state, detail = fresh(repo)["x"]
    assert state == "STALE" and detail.startswith("src/app.py changed in ")


def test_commit_elsewhere_keeps_it_fresh(repo):
    stamped(repo)
    (repo / "other.txt").write_text("x")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-qm", "other")
    assert fresh(repo)["x"][0] == "FRESH"


def test_uncommitted_edit_makes_it_stale(repo):
    stamped(repo)
    time.sleep(1.1)  # verification is stamped to the second; this edit comes after it
    (repo / "src" / "app.py").write_text("def resolve_peers():\n    return 3\n")
    assert fresh(repo)["x"] == ("STALE", "uncommitted change to src/app.py")


def test_unknown_commit_falls_back_to_dates(repo):
    concept(repo, "x", meta="type: gotcha\ntitle: X\ndescription: d\nverified:\n"
            "  - {by: okf-wiki/haiku, at: 2020-01-01T00:00:00Z, commit: deadbeefdead}\n")
    assert fresh(repo)["x"][0] == "STALE"  # init commit is newer than 2020
    concept(repo, "y", meta="type: gotcha\ntitle: Y\ndescription: d\nverified:\n"
            "  - {by: okf-wiki/haiku, at: 2999-01-01T00:00:00Z, commit: deadbeefdead}\n")
    assert fresh(repo)["y"][0] == "FRESH"


def test_unanchored_and_unverified(repo):
    concept(repo, "n", body="\n## Verify\n\n- none: vendor behaviour\n")
    concept(repo, "u")
    res = fresh(repo)
    assert res["n"][0] == "UNANCHORED"
    assert res["u"] == ("UNVERIFIED", "no verified commit")


def test_fresh_cli_lists_states(repo):
    stamped(repo)
    r = run(repo, "fresh")
    assert r.stdout.splitlines()[0] == "FRESH x"
    assert r.stdout.splitlines()[-1] == "okf: fresh ok 1 fresh, 0 stale, 0 unanchored, 0 unverified"


def test_anchor_symbol_and_count(repo):
    concept(repo, "ok", body="\n## Verify\n\n- `src/app.py` :: `resolve_peers`\n"
            "- `src/app.py` :: /^def / => 1\n")
    r = run(repo, "anchor", "ok")
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "okf: anchor confirmed ok"
    concept(repo, "bad", body="\n## Verify\n\n- `src/app.py` :: /^def / => 2\n")
    r = run(repo, "anchor", "bad")
    assert r.returncode == 1 and "matched 1x" in r.stdout


def test_anchor_refuses_paths_outside_the_repo(repo):
    ok, msg = okf.eval_anchor(repo, okf.Anchor("../etc/passwd", "symbol", "root"))
    assert not ok and "outside the repository" in msg


def test_anchor_none_is_ok(repo):
    concept(repo, "n", body="\n## Verify\n\n- none: vendor behaviour\n")
    r = run(repo, "anchor", "n")
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "okf: anchor none n"


def test_merged_branch_changing_an_anchor_file_makes_it_stale(repo, monkeypatch):
    # A feature branch edits the anchored file before the concept is verified on main, and is
    # merged after: its commit is new to the verified commit's history even though it is older.
    git(repo, "checkout", "-qb", "feature")
    (repo / "src" / "app.py").write_text("def resolve_peers():\n    return 9\n")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2020-01-02T00:00:00Z")
    git(repo, "commit", "-qam", "feature edit")
    monkeypatch.delenv("GIT_COMMITTER_DATE")
    git(repo, "checkout", "-q", "main")
    stamped(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "wiki")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
    state, detail = fresh(repo)["x"]
    assert state == "STALE" and detail.startswith("src/app.py changed in ")


def test_dot_slash_anchor_paths_still_go_stale(repo):
    stamped(repo, body=GOOD_BODY.replace("`src/app.py`", "`./src/app.py`"))
    commit_app(repo, "def resolve_peers():\n    return 2\n")
    assert fresh(repo)["x"][0] == "STALE"


def test_capturing_code_and_concept_in_one_commit_stays_fresh(repo):
    (repo / "src" / "app.py").write_text("def resolve_peers():\n    return 5\n")
    stamped(repo)                                   # verified against the dirty working tree
    assert fresh(repo)["x"][0] == "FRESH"           # concept and code are changing together
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "fix and capture")
    assert fresh(repo)["x"][0] == "FRESH"
