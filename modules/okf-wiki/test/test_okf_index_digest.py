from okf_testlib import concept, okf, run


def meta(t, title, desc, extra=""):
    return f"type: {t}\ntitle: {title}\ndescription: {desc}\n{extra}"


def test_index_groups_by_type_in_fixed_order_and_sorts_titles(repo):
    concept(repo, "zeta", meta=meta("decision", "Use pnpm", "We use pnpm because X."))
    concept(repo, "beta", meta=meta("gotcha", "b trap", "B breaks."))
    concept(repo, "alpha", meta=meta("gotcha", "A trap", "A breaks.", "status: deprecated\n"))
    r = run(repo, "index")
    assert r.stdout.splitlines()[-1] == "okf: index written 1 files"
    assert (repo / ".wiki" / "index.md").read_text() == (
        '---\nokf_version: "0.2"\n---\n\n'
        "# Gotcha\n\n"
        "* [A trap](./alpha.md) - A breaks. (deprecated)\n"
        "* [b trap](./beta.md) - B breaks.\n\n"
        "# Decision\n\n"
        "* [Use pnpm](./zeta.md) - We use pnpm because X.\n"
    )


def test_index_is_byte_stable_and_only_written_on_change(repo):
    concept(repo, "a")
    run(repo, "index")
    first = (repo / ".wiki" / "index.md").read_bytes()
    r = run(repo, "index")
    assert r.stdout.splitlines()[-1] == "okf: index unchanged 0 files"
    assert (repo / ".wiki" / "index.md").read_bytes() == first


def test_index_ignores_a_conflicted_old_index(repo):
    concept(repo, "a")
    (repo / ".wiki" / "index.md").write_text("<<<<<<< HEAD\njunk\n=======\n>>>>>>> x\n")
    run(repo, "index")
    assert "<<<<<<<" not in (repo / ".wiki" / "index.md").read_text()


def test_subdirectories_get_their_own_index(repo):
    concept(repo, "gotchas/one", meta=meta("gotcha", "One", "One breaks."))
    concept(repo, "top", meta=meta("reference", "Top", "Top facts."))
    run(repo, "index")
    root = (repo / ".wiki" / "index.md").read_text()
    assert "# Subdirectories\n\n* [gotchas](./gotchas/index.md) - 1 concepts\n" in root
    assert (repo / ".wiki" / "gotchas" / "index.md").read_text() == (
        "# Gotcha\n\n* [One](./one.md) - One breaks.\n")


def test_digest_lists_claims_marks_stale_and_excludes_invalid_and_deprecated(repo):
    concept(repo, "good", meta=meta("gotcha", "Good", "Good claim."))
    concept(repo, "old", meta=meta("gotcha", "Old", "Old claim.", "status: deprecated\n"))
    concept(repo, "bad", meta="title: no type\n")
    concepts = okf.load(repo / ".wiki")
    text = okf.digest(concepts, okf.check_bundle(repo / ".wiki", concepts), {"good"}, False)
    lines = text.splitlines()
    assert lines[0].startswith("okf-wiki:digest v1 · .wiki/ · 1 concepts (1 stale ⚠, 1 invalid")
    assert lines[1] == okf.RULE
    assert "okf-wiki: invalid concepts excluded until fixed: bad (run okf.py validate)" in lines
    assert "- ⚠ [gotcha] good — Good claim." in lines
    assert not any("old" in line.split(" — ")[0] for line in lines[3:])


def test_digest_on_empty_bundle_says_so(repo):
    text = okf.digest([], [], set(), False)
    assert "Empty wiki: run the okf-wiki ingest skill" in text


def test_digest_reflect_due_shows_in_header(repo):
    concept(repo, "a")
    concepts = okf.load(repo / ".wiki")
    assert "reflect due" in okf.digest(concepts, [], set(), True).splitlines()[0]


def test_digest_degrades_to_titles_then_truncates_within_budget(repo, monkeypatch):
    long = "word " * 38
    for i in range(60):
        concept(repo, f"c{i:02d}", meta=meta("gotcha", f"T{i:02d}", long.strip()))
    concepts = okf.load(repo / ".wiki")
    text = okf.digest(concepts, [], set(), False)
    assert len(text) <= okf.DIGEST_BUDGET
    assert "- [gotcha] c00 — T00" in text  # titles, not descriptions
    monkeypatch.setattr(okf, "DIGEST_BUDGET", 1200)
    text = okf.digest(concepts, [], set(), False)
    assert len(text) <= 1200
    assert text.rstrip().endswith("more: see .wiki/index.md")
