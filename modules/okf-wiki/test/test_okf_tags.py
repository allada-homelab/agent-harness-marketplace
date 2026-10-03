import pytest
from okf_testlib import GOOD_META, concept, git, run


def tagged(repo, cid, tags, title=None):
    meta = GOOD_META.replace("tags: [pnpm, deps]", f"tags: [{', '.join(tags)}]")
    if title:
        meta = meta.replace("title: pnpm drops peer deps of linked modules", f"title: {title}")
    return concept(repo, cid, meta=meta)


def test_tags_lists_every_tag_by_count(repo):
    tagged(repo, "a", ["pnpm", "deps"])
    tagged(repo, "b", ["pnpm"])
    concept(repo, "broken", meta="type: [unclosed\n")
    r = run(repo, "tags")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines() == ["2 pnpm", "1 deps", "okf: tags ok 2 tags (1 used once) in 2 concepts"]


def test_tags_named_lists_the_concepts_carrying_each(repo):
    tagged(repo, "a", ["pnpm", "deps"], title="Alpha")
    tagged(repo, "b", ["pnpm"], title="Beta")
    r = run(repo, "tags", "pnpm", "nope")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines() == ["pnpm a — Alpha", "pnpm b — Beta", "nope: no concepts",
                                     "okf: tags ok 2 concepts"]


def test_tags_suggest_merges_variants_into_the_more_used_tag(repo):
    tagged(repo, "a", ["worktree", "pre-commit"])
    tagged(repo, "b", ["worktree", "precommit"])
    tagged(repo, "c", ["worktrees"])
    assert run(repo, "tags", "--suggest").stdout.splitlines() == [
        "MERGE? pre-commit (1) -> precommit (1): spelling",
        "MERGE? worktrees (1) -> worktree (2): plural",
        "okf: tags ok 2 suggestions",
    ]


def test_tags_suggest_leaves_acronyms_to_judgment(repo):
    # ha is high-availability in one wiki and home-assistant in another; a script cannot tell
    tagged(repo, "a", ["ha", "high-availability", "home-assistant"])
    assert run(repo, "tags", "--suggest").stdout.splitlines() == ["okf: tags ok 0 suggestions"]


def test_tags_suggest_never_proposes_a_malformed_target(repo):
    tagged(repo, "a", ["Kubernetes"])
    tagged(repo, "b", ["Kubernetes"])
    tagged(repo, "c", ["kubernetes"])
    assert "MERGE? Kubernetes (2) -> kubernetes (1): spelling" in run(repo, "tags", "--suggest").stdout


def test_tags_suggest_flags_redundant_and_malformed_tags(repo):
    # make_repo names the repository directory `repo`
    tagged(repo, "a", ["gotcha", "repo", "daemon.json"])
    assert run(repo, "tags", "--suggest").stdout.splitlines() == [
        "FORMAT daemon.json (1): tags are lowercase-kebab like ids",
        "REDUNDANT gotcha (1): it is a concept type, which `type` already records",
        "REDUNDANT repo (1): it is the repository's name",
        "okf: tags ok 3 suggestions",
    ]


def test_tags_suggest_names_the_repo_from_a_linked_worktree(repo):
    tagged(repo, "a", ["repo"])
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "wiki")
    git(repo, "worktree", "add", "-q", str(repo.parent / "feat-x"))
    out = run(repo.parent / "feat-x", "tags", "--suggest").stdout
    assert "REDUNDANT repo (1): it is the repository's name" in out


def test_tags_suggest_on_a_clean_vocabulary(repo):
    tagged(repo, "a", ["pnpm", "deps"])
    assert run(repo, "tags", "--suggest").stdout.splitlines() == ["okf: tags ok 0 suggestions"]


def test_retag_renames_and_merges_without_duplicating(repo):
    tagged(repo, "a", ["worktrees", "git"])
    tagged(repo, "b", ["worktree", "worktrees"])
    tagged(repo, "c", ["git"])
    before = (repo / ".wiki/c.md").read_text()
    r = run(repo, "retag", "worktrees", "worktree")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == "okf: retag ok worktrees -> worktree (2 concepts)"
    assert "tags: [worktree, git]" in (repo / ".wiki/a.md").read_text()
    assert "tags: [worktree]" in (repo / ".wiki/b.md").read_text()
    assert (repo / ".wiki/c.md").read_text() == before
    assert run(repo, "validate").returncode == 0


def test_retag_drop_removes_the_tag(repo):
    tagged(repo, "a", ["gotcha", "git"])
    r = run(repo, "retag", "gotcha", "--drop")
    assert r.stdout.splitlines()[-1] == "okf: retag ok gotcha dropped (1 concepts)"
    assert "tags: [git]" in (repo / ".wiki/a.md").read_text()


@pytest.mark.parametrize("args, msg", [
    (["nope", "x"], "no concept is tagged 'nope'"),
    (["git", "Bad_Tag"], "must match"),
    (["git", "git"], "same tag"),
    (["git"], "give a new tag or --drop"),
    (["git", "x", "--drop"], "give a new tag or --drop"),
])
def test_retag_refuses(repo, args, msg):
    tagged(repo, "a", ["git"])
    r = run(repo, "retag", *args)
    assert r.returncode == 2
    assert msg in r.stdout
