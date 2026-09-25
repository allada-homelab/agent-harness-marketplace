from okf_testlib import concept, okf, run


def test_mv_renames_and_rewrites_inbound_and_outbound_links(repo):
    concept(repo, "target")
    concept(repo, "linker", body="\nSee [the trap](./target.md#why).\n\n## Verify\n\n- none: x\n")
    concept(repo, "mover", body="\nRelated: [linker](./linker.md).\n\n## Verify\n\n- none: x\n")
    r = run(repo, "mv", "target", "gotchas/target")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == "okf: mv ok target -> gotchas/target (1 files relinked)"
    assert "[the trap](./gotchas/target.md#why)" in (repo / ".wiki/linker.md").read_text()
    run(repo, "mv", "mover", "gotchas/mover")
    assert "[linker](../linker.md)" in (repo / ".wiki/gotchas/mover.md").read_text()
    assert not (repo / ".wiki/target.md").exists()
    assert "gotchas/index.md" in (repo / ".wiki/index.md").read_text()
    assert run(repo, "validate").stdout.count("broken link") == 0


def test_mv_refuses_bad_or_taken_targets(repo):
    concept(repo, "a")
    concept(repo, "b")
    assert "already exists" in run(repo, "mv", "a", "b").stdout
    assert run(repo, "mv", "a", "Bad").returncode == 2
    assert "no concept" in run(repo, "mv", "zzz", "c").stdout


LLM_WIKI = """---
type: Gotcha
title: Alerter delivers to nobody
description: A green alerter can have zero subscribers.
tags:
  - alerting
  - ntfy
generated: { by: llm-wiki/unknown, at: 2026-06-27 }
verified: { by: llm-wiki/unknown, at: 2026-07-01T00:00:00Z }
---
# Alerter delivers to nobody

Body text.

## Verify

- `grep -n "subscribers" src/app.py` — expected: present.
- `src/app.py:resolve_peers` — the function exists.
- not code-verifiable; check the dashboard by hand.

## Related

- [x](./other.md)
"""


def test_migrate_converts_an_llm_wiki_concept(repo, tmp_path):
    src = tmp_path / "old"
    src.mkdir()
    (src / "Alerter_Nobody.md").write_text(LLM_WIKI)
    (src / "weird.md").write_text("---\ntype: concept\ntitle: W\n---\nbody\n")
    (src / "index.md").write_text("# Index\n")
    r = run(repo, "migrate", str(src))
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout.splitlines()
    assert "MIGRATED Alerter_Nobody -> alerter-nobody" in out
    assert any(line.startswith("MIGRATED weird -> weird (NEEDS REVIEW: type 'concept'") for line in out)
    assert out[-1] == "okf: migrate ok 2 migrated, 1 need review, 0 skipped"
    c = okf.find(okf.load(repo / ".wiki"), "alerter-nobody")
    assert c.meta["type"] == "gotcha"
    assert c.meta["generated"] == {"by": "process:okf-wiki-migrate", "at": "2026-06-27T00:00:00Z"}
    assert c.meta["verified"] == [{"by": "process:okf-wiki-migrate", "at": "2026-07-01T00:00:00Z"}]
    assert c.meta["tags"] == ["alerting", "ntfy"]
    anchors, bad, _ = okf.parse_anchors(c.body)
    assert [(a.path, a.needle) for a in anchors] == [("src/app.py", "subscribers"), ("src/app.py", "resolve_peers")]
    assert bad == []
    assert "## Legacy verification\n\n- not code-verifiable; check the dashboard by hand.\n" in c.body
    assert "## Related" in c.body
    errs = [f for f in okf.check_concept(c) if f.level == "error"]
    assert errs == []


def test_migrate_dry_run_writes_nothing_and_skips_collisions(repo, tmp_path):
    src = tmp_path / "old"
    src.mkdir()
    (src / "a.md").write_text("---\ntype: gotcha\ntitle: A\n---\nbody\n")
    (src / "b.md").write_text("---\ntype: [x\n---\n")
    r = run(repo, "migrate", str(src), "--dry-run")
    assert r.stdout.splitlines()[-1] == "okf: migrate dry-run 1 migrated, 0 need review, 1 skipped"
    assert not (repo / ".wiki/a.md").exists()
    concept(repo, "a")
    assert "SKIPPED a (a already exists)" in run(repo, "migrate", str(src)).stdout


def test_migrate_takes_a_missing_title_from_the_h1(repo, tmp_path):
    src = tmp_path / "old"
    src.mkdir()
    (src / "no-title.md").write_text("---\ntype: reference\nname: no-title\n---\n# The real title\n\nBody.\n")
    run(repo, "migrate", str(src))
    assert okf.find(okf.load(repo / ".wiki"), "no-title").meta["title"] == "The real title"
