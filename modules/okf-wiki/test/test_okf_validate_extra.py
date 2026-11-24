from okf_testlib import GOOD_BODY, GOOD_META, concept, okf


def warns(repo, cid):
    c = okf.find(okf.load(repo / ".wiki"), cid)
    return [f.msg for f in okf.check_concept(c) if f.level == "warn"]


def test_anchor_paths_must_be_repo_relative(repo):
    body = GOOD_BODY.replace("- `src/app.py` :: `resolve_peers`",
                             "- `/opt/tool/cli.py` :: `main`\n- `../elsewhere.py` :: `x`\n"
                             f"- `{repo}/src/app.py` :: `resolve_peers`\n- `src/app.py` :: `resolve_peers`")
    concept(repo, "sub/abs", body=body)
    w = warns(repo, "sub/abs")
    assert "anchor path /opt/tool/cli.py is not repo-relative; freshness cannot check it" in w
    assert "anchor path ../elsewhere.py is not repo-relative; freshness cannot check it" in w
    assert f"anchor path {repo}/src/app.py is not repo-relative; freshness cannot check it" in w
    assert not any("anchor path src/app.py" in m for m in w)


def test_a_tag_repeating_the_type_warns(repo):
    concept(repo, "t", meta=GOOD_META.replace("tags: [pnpm, deps]", "tags: [pnpm, gotcha]"))
    assert "tag 'gotcha' repeats the concept's type" in warns(repo, "t")
    concept(repo, "ok", meta=GOOD_META.replace("tags: [pnpm, deps]", "tags: [pnpm, decision]"))
    assert not any("repeats" in m for m in warns(repo, "ok"))


def test_word_count_skips_code_fences_and_verification_sections(repo):
    prose = " ".join(["word"] * 380)
    fence = "```sh\n" + " ".join(["code"] * 200) + "\n```\n"
    legacy = "## Legacy verification\n\n" + " ".join(["old"] * 100) + "\n"
    concept(repo, "fits", body=f"\n# T\n\n{prose}\n\n{fence}\n## Verify\n\n- `src/app.py` :: `resolve_peers`\n\n{legacy}")
    assert not any("words" in m for m in warns(repo, "fits"))
    concept(repo, "long", body=f"\n# T\n\n{prose} {' '.join(['more'] * 30)}\n\n## Verify\n\n- none: x\n")
    assert any(m.startswith("body is 412 words") for m in warns(repo, "long"))


def test_body_warning_names_the_longest_section_and_the_overage(repo):
    big, small = " ".join(["a"] * 298), " ".join(["b"] * 148)  # +2 heading words each = 300 and 150
    concept(repo, "two", body=f"\n## Big\n\n{big}\n\n## Small\n\n{small}\n\n## Verify\n\n- none: x\n")
    (msg,) = [m for m in warns(repo, "two") if m.startswith("body is")]
    assert msg == ('body is 450 words, 50 over 400; longest section "Big" has 300 — '
                   "advisory: trim once or split into two concepts, never loop")
