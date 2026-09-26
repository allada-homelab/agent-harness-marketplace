from okf_testlib import GOOD_BODY, GOOD_META, concept, git, okf, run


def test_new_scaffolds_a_template_that_fails_validate_until_filled(repo):
    r = run(repo, "new", "gotcha", "cache-trap", "--title", "Cache trap")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1].startswith("okf: new created cache-trap ")
    text = (repo / ".wiki" / "cache-trap.md").read_text()
    for section in ("## Symptom", "## What fails", "## What works", "## Why", "## Verify"):
        assert section in text
    assert run(repo, "validate").returncode == 1  # <fill: …> placeholders remain
    assert "cache-trap" in (repo / ".wiki" / "index.md").read_text()


def test_new_creates_the_bundle_when_missing(repo):
    (repo / ".wiki").rmdir()
    assert run(repo, "new", "decision", "use-pnpm").returncode == 0
    assert (repo / ".wiki" / "use-pnpm.md").exists()


def test_new_refuses_bad_type_bad_slug_and_existing(repo):
    concept(repo, "taken")
    assert run(repo, "new", "Gotcha", "x").returncode == 2
    assert run(repo, "new", "gotcha", "Bad_Slug").returncode == 2
    r = run(repo, "new", "gotcha", "taken")
    assert r.returncode == 2 and "already exists" in r.stdout


def test_new_flags_near_duplicates_unless_forced(repo):
    concept(repo, "pnpm-peer-trap")
    r = run(repo, "new", "gotcha", "pnpm-peer-deps", "--title", "pnpm peer deps vanish")
    assert r.returncode == 3
    assert "DUPLICATE? pnpm-peer-trap" in r.stdout
    assert run(repo, "new", "gotcha", "pnpm-peer-deps", "--force").returncode == 0


def test_stamp_verified_records_actor_time_and_head(repo):
    concept(repo, "pnpm-peer-trap")
    r = run(repo, "stamp", "pnpm-peer-trap", "--by", "okf-wiki/haiku", "--generated", "--verified")
    assert r.returncode == 0, r.stdout + r.stderr
    meta = okf.load(repo / ".wiki")[0].meta
    head = okf.head_commit(repo)
    assert meta["generated"]["by"] == "okf-wiki/haiku"
    assert okf.TS_RE.match(meta["generated"]["at"])
    assert meta["verified"][-1]["commit"] == head
    assert list(meta)[:3] == ["type", "title", "description"]  # key order preserved


def test_stamp_verified_refuses_when_an_anchor_is_broken(repo):
    concept(repo, "x", body=GOOD_BODY.replace("resolve_peers", "gone_symbol"))
    r = run(repo, "stamp", "x", "--by", "okf-wiki/haiku", "--verified")
    assert r.returncode == 2
    assert "anchors do not hold" in r.stdout


def test_stamp_refuses_errors_bad_actor_and_unconfirmed_human(repo):
    concept(repo, "x")
    concept(repo, "y", body=GOOD_BODY + "\n<fill: todo>\n")
    assert "must be okf-wiki/" in run(repo, "stamp", "x", "--by", "claude", "--generated").stdout
    assert "--human-confirmed" in run(repo, "stamp", "x", "--by", "human:dave", "--verified").stdout
    assert run(repo, "stamp", "x", "--by", "human:dave", "--verified", "--human-confirmed").returncode == 0
    assert "fix validate errors first" in run(repo, "stamp", "y", "--by", "okf-wiki/haiku", "--generated").stdout
    assert "pass --generated, --verified" in run(repo, "stamp", "x", "--by", "okf-wiki/haiku").stdout


def test_stamp_keeps_the_newest_five_verifications(repo):
    concept(repo, "x")
    for _ in range(7):
        run(repo, "stamp", "x", "--by", "okf-wiki/haiku", "--verified")
    assert len(okf.load(repo / ".wiki")[0].meta["verified"]) == 5


def test_stamp_preserves_unknown_keys(repo):
    concept(repo, "x", meta=GOOD_META + "team: platform\n")
    assert run(repo, "stamp", "x", "--by", "okf-wiki/haiku", "--generated").returncode == 0
    meta = okf.load(repo / ".wiki")[0].meta
    assert meta["team"] == "platform" and meta["generated"]["by"] == "okf-wiki/haiku"


def test_new_check_reports_without_writing(repo):
    concept(repo, "pnpm-peer-trap")
    r = run(repo, "new", "gotcha", "cache-trap", "--check")
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "okf: new available cache-trap"
    assert not (repo / ".wiki" / "cache-trap.md").exists()
    r = run(repo, "new", "gotcha", "pnpm-peer-deps", "--title", "pnpm peer deps vanish", "--check")
    assert r.returncode == 3 and "DUPLICATE? pnpm-peer-trap" in r.stdout


def test_refusal_is_one_line_even_when_git_says_more(tmp_path):
    r = tmp_path / "empty"
    r.mkdir()
    git(r, "init", "-q")
    (r / ".wiki").mkdir()
    concept(r, "a", body="\n## Verify\n\n- none: x\n")
    out = run(r, "stamp", "a", "--by", "okf-wiki/haiku", "--verified").stdout.splitlines()
    assert len(out) == 1 and out[0].startswith("okf: stamp refused git rev-parse HEAD failed")


def _meta_with(description, title):
    return GOOD_META.replace(
        "description: Linked modules lose peer deps under pnpm; add them to the root package.json because hoisting skips links.",
        f"description: {description}").replace("title: fix peer deps}", f"title: {title}}}")


def test_stamp_round_trips_a_description_with_a_hash_after_an_escaped_quote(repo):
    # The writer escapes a `"` as `\"`; the comment stripper must honour that escape, or
    # the next read cuts the value at ` #` and the following stamp writes the stump back.
    for cid, raw, want in (
            ("dq", r'"Pin \"uv\" #12 or the cache misses"', 'Pin "uv" #12 or the cache misses'),
            ("sq", "'It''s the #1 trap, not the second'", "It's the #1 trap, not the second")):
        concept(repo, cid, meta=_meta_with(raw, "fix peer deps"))
        for _ in range(2):
            r = run(repo, "stamp", cid, "--by", "okf-wiki/haiku", "--generated", "--verified")
            assert r.returncode == 0, r.stdout + r.stderr
            meta = {c.id: c for c in okf.load(repo / ".wiki")}[cid].meta
            assert meta["description"] == want
    assert run(repo, "validate").returncode == 0


def test_stamp_round_trips_source_titles_with_commas_quotes_and_hashes(repo):
    titles = {"plain": ('"fix a, b and c"', "fix a, b and c"),
              "revert": (r'"Revert \"fix #12, keep peers\""', 'Revert "fix #12, keep peers"')}
    for cid, (raw, _) in titles.items():
        concept(repo, cid, meta=_meta_with("d", raw))
    for cid, (_, want) in titles.items():
        for _ in range(2):
            r = run(repo, "stamp", cid, "--by", "okf-wiki/haiku", "--generated", "--verified")
            assert r.returncode == 0, r.stdout + r.stderr
            meta = {c.id: c for c in okf.load(repo / ".wiki")}[cid].meta
            assert meta["sources"] == [{"id": "s1", "resource": "commit:e4132f6", "title": want}]
    r = run(repo, "validate")
    assert r.returncode == 0, r.stdout
