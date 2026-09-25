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
