from okf_testlib import concept, okf, run

LEGACY_LINES = [
    ("- `grep -n 'resolve_peers' src/app.py` — expected: present.", "- `src/app.py` :: `resolve_peers`"),
    ('- grep -F "return 1" src/app.py  # the default', "- `src/app.py` :: `return 1`"),
    ("- `grep -c \"def resolve_peers\" src/app.py`", "- `src/app.py` :: `def resolve_peers`"),
    ("- `src/app.py:resolve_peers` — the function exists.", "- `src/app.py` :: `resolve_peers`"),
    ("- see `src/app.py:return 1` in the body", "- `src/app.py` :: `return 1`"),
]
KEPT = [
    "- `grep -n 'resolve_peers' src/gone.py`",      # path not in the repo
    "- `grep 'not_in_the_file' src/app.py`",          # the anchor would fail
    "- `src/app.py:2` — the return line",            # a line number, not a symbol
    "- `grep -n 'x' /opt/tool/cli.py`",              # outside the repo
    "- not code-verifiable; check the dashboard by hand.",
]


def test_legacy_anchor_converts_only_holding_repo_anchors(repo):
    for line, want in LEGACY_LINES:
        assert okf.legacy_anchor(repo, line.lstrip("- ")) == want, line
    for line in KEPT:
        assert okf.legacy_anchor(repo, line.lstrip("- ")) is None, line


def test_migrate_maps_one_line_and_keeps_unconvertible_lines_legacy(repo, tmp_path):
    src = tmp_path / "old"
    src.mkdir()
    verify = "\n".join([LEGACY_LINES[0][0], *KEPT])
    (src / "a.md").write_text(f"---\ntype: gotcha\ntitle: A\none-line: A short claim.\n---\n# A\n\n## Verify\n\n{verify}\n")
    (src / "b.md").write_text("---\ntype: gotcha\ntitle: B\ndescription: Kept.\none-line: Ignored.\n---\n"
                              "# B\n\n## Verify\n\n- `grep 'nope' src/gone.py`\n")
    assert run(repo, "migrate", str(src)).returncode == 0
    cs = {c.id: c for c in okf.load(repo / ".wiki")}
    a, b = cs["a"], cs["b"]
    assert a.meta["description"] == "A short claim." and "one-line" not in a.meta
    assert [(x.path, x.needle) for x in okf.parse_anchors(a.body)[0]] == [("src/app.py", "resolve_peers")]
    assert all(line in a.body.split("## Legacy verification", 1)[1] for line in KEPT)
    assert b.meta["description"] == "Kept." and b.meta["one-line"] == "Ignored."
    assert "- none: migrated from llm-wiki; see Legacy verification" in b.body


MIGRATED = """
# Old

Body.

## Verify

- none: migrated from llm-wiki; see Legacy verification

## Legacy verification

{lines}

## Related

- see also
"""


def test_anchors_from_legacy_upgrades_a_migrated_bundle_idempotently(repo):
    lines = "\n".join([*(line for line, _ in LEGACY_LINES), KEPT[0], KEPT[4]])
    p = concept(repo, "old", meta="type: gotcha\ntitle: Old\ndescription: d\n", body=MIGRATED.format(lines=lines))
    concept(repo, "plain")                                   # no legacy section: untouched
    before = p.read_text()
    r = run(repo, "migrate", "--anchors-from-legacy", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ANCHOR old - `src/app.py` :: `resolve_peers`" in r.stdout.splitlines()
    assert r.stdout.splitlines()[-1] == "okf: migrate dry-run 3 anchors from legacy in 1 concepts"
    assert p.read_text() == before
    r = run(repo, "migrate", "--anchors-from-legacy")
    assert r.stdout.splitlines()[-1] == "okf: migrate ok 3 anchors from legacy in 1 concepts"
    c = okf.find(okf.load(repo / ".wiki"), "old")
    anchors, bad, none = okf.parse_anchors(c.body)
    assert [(x.path, x.needle) for x in anchors] == [
        ("src/app.py", "resolve_peers"), ("src/app.py", "return 1"), ("src/app.py", "def resolve_peers")]
    assert not none and bad == []
    legacy = c.body.split("## Legacy verification", 1)[1].split("## Related")[0]
    assert legacy.strip().splitlines() == [KEPT[0], KEPT[4]]
    assert c.body.rstrip().endswith("## Related\n\n- see also")
    after = p.read_text()
    r = run(repo, "migrate", "--anchors-from-legacy")
    assert r.stdout.splitlines()[-1] == "okf: migrate ok 0 anchors from legacy in 0 concepts"
    assert p.read_text() == after
    assert not any(f.level == "error" for f in okf.check_concept(c))


def test_anchors_from_legacy_drops_an_emptied_legacy_section(repo):
    p = concept(repo, "old", meta="type: gotcha\ntitle: Old\ndescription: d\n",
                body=MIGRATED.format(lines=LEGACY_LINES[0][0]).split("\n## Related")[0])
    assert run(repo, "migrate", "--anchors-from-legacy").returncode == 0
    text = p.read_text()
    assert "Legacy verification" not in text and "- none:" not in text
    assert text.endswith("## Verify\n\n- `src/app.py` :: `resolve_peers`\n")


def test_migrate_without_a_source_or_the_flag_refuses(repo):
    r = run(repo, "migrate")
    assert r.returncode == 2 and "--anchors-from-legacy" in r.stdout


def test_anchors_from_legacy_refuses_a_source_directory(repo, tmp_path):
    (tmp_path / "old").mkdir()
    r = run(repo, "migrate", str(tmp_path / "old"), "--anchors-from-legacy")
    assert r.returncode == 2
    assert r.stdout.splitlines()[-1].startswith("okf: migrate refused --anchors-from-legacy upgrades")
