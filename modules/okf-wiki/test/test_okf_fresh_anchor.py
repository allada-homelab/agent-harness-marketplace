import subprocess
import time

from okf_testlib import GOOD_BODY, GOOD_META, concept, git, okf, run


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


def many_commits(repo, n):
    """n commits, each adding src/mNNN.py, via fast-import: a commit loop is too slow for a test."""
    stream = []
    for i in range(n):
        data = f"def f{i:03d}():\n    return {i}\n"
        stream += ["commit refs/heads/main", "committer t <t@example.com> 1790000000 +0000", "data 1", "c"]
        stream += ["from refs/heads/main^0"] if i == 0 else []
        stream += [f"M 100644 inline src/m{i:03d}.py", f"data {len(data)}", data]
    subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"], input="\n".join(stream) + "\n",
                   text=True, check=True)
    git(repo, "reset", "-q", "--hard", "main")
    out = subprocess.run(["git", "-C", str(repo), "rev-list", "--reverse", "main"],
                         capture_output=True, text=True, check=True).stdout.split()
    return out[-n:]


def test_freshness_of_250_concepts_at_distinct_commits_fits_the_session_start_budget(repo):
    shas = many_commits(repo, 250)
    for i, sha in enumerate(shas):
        concept(repo, f"c{i:03d}", meta=f"type: gotcha\ntitle: T{i}\ndescription: claim {i}\nverified:\n"
                f"  - {{by: okf-wiki/haiku, at: 2026-09-01T00:00:00Z, commit: {sha[:12]}}}\n",
                body=f"\nBody.\n\n## Verify\n\n- `src/m{i:03d}.py` :: `f{i:03d}`\n")
    commit_file = repo / "src" / "m007.py"
    commit_file.write_text("def f007():\n    return -1\n")
    git(repo, "commit", "-qam", "change m007")
    concepts = okf.load(repo / ".wiki")
    t = time.perf_counter()
    res = okf.freshness(repo, concepts, timeout=0.3)  # the SessionStart budget
    # Per-call timeouts never fire on many fast calls; the budget is the total.
    assert time.perf_counter() - t < 0.3
    assert [c for c, (s, _) in res.items() if s == "STALE"] == ["c007"]
    assert sum(s == "FRESH" for s, _ in res.values()) == 249


def test_digest_says_when_freshness_was_not_checked(repo):
    concept(repo, "a")
    cs = okf.load(repo / ".wiki")
    assert "freshness unchecked" in okf.digest(cs, [], None, False).splitlines()[0]
    assert "freshness unchecked" not in okf.digest(cs, [], set(), False).splitlines()[0]


def test_anchor_paths_outside_the_repo_do_not_break_freshness(repo):
    outside = GOOD_BODY.replace("- `src/app.py` :: `resolve_peers`",
                                "- `/opt/tool/cli.py` :: `main`\n- `../elsewhere.py` :: `x`")
    both = outside.replace("- `../elsewhere.py` :: `x`", "- `src/app.py` :: `resolve_peers`")
    meta = GOOD_META + f"verified:\n  - {{by: x/y, at: 2026-01-01T00:00:00Z, commit: {okf.head_commit(repo)}}}\n"
    concept(repo, "only-outside", meta=meta, body=outside)  # as migrate writes them; stamp refuses these
    concept(repo, "mixed", meta=meta, body=both)
    commit_app(repo, "def resolve_peers():\n    return 2\n")
    res = fresh(repo)
    assert res["only-outside"][0] == "UNANCHORED"
    assert res["mixed"][0] == "STALE"


def test_a_vanished_verified_commit_still_falls_back_to_dates_beside_a_present_one(repo, monkeypatch):
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-08-01T00:00:00Z")
    commit_app(repo, "def resolve_peers():\n    return 2\n", "older than the present stamp")
    monkeypatch.delenv("GIT_COMMITTER_DATE")
    (repo / "src/other.py").write_text("def other():\n    return 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "other")
    squashed = GOOD_META + "verified:\n  - {by: x/y, at: 2026-07-01T00:00:00Z, commit: deadbeef1234}\n"
    present = GOOD_META + f"verified:\n  - {{by: x/y, at: 2026-09-01T00:00:00Z, commit: {okf.head_commit(repo)}}}\n"
    concept(repo, "squashed", meta=squashed)  # anchored on src/app.py, changed after its date
    concept(repo, "present", meta=present, body=GOOD_BODY.replace("src/app.py", "src/other.py")
            .replace("resolve_peers", "other"))
    res = fresh(repo)
    assert res["squashed"][0] == "STALE" and res["present"][0] == "FRESH"
