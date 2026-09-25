from okf_testlib import GOOD_BODY, GOOD_META, concept, okf, run


def findings(repo):
    return okf.check_bundle(repo / ".wiki", okf.load(repo / ".wiki"))


def msgs(repo, level):
    return [f"{f.id}: {f.msg}" for f in findings(repo) if f.level == level]


def test_good_concept_is_clean(repo):
    concept(repo, "pnpm-peer-trap")
    assert findings(repo) == []
    r = run(repo, "validate")
    assert r.returncode == 0
    assert r.stdout.splitlines()[-1] == "okf: validate ok 1 concepts, 0 warnings"


def test_missing_and_unknown_type_are_errors(repo):
    concept(repo, "a", meta="title: A\n")
    concept(repo, "b", meta="type: Gotcha\ntitle: B\n")
    errs = msgs(repo, "error")
    assert "a: `type` is required" in errs
    assert any(e.startswith("b: type 'Gotcha' is not one of") for e in errs)
    assert run(repo, "validate").returncode == 1


def test_bad_frontmatter_is_an_error(repo):
    (repo / ".wiki" / "broken.md").write_text("---\ntype: [x\n---\nbody\n")
    assert any("frontmatter:" in e for e in msgs(repo, "error"))


def test_bad_id_is_an_error(repo):
    concept(repo, "Bad_Name")
    assert any("id segment 'Bad_Name'" in e for e in msgs(repo, "error"))


def test_unfilled_template_is_an_error(repo):
    concept(repo, "t", body=GOOD_BODY + "\n<fill: symptom>\n")
    assert any("unfilled" in e for e in msgs(repo, "error"))


def test_secrets_are_errors_but_placeholders_are_not(repo):
    concept(repo, "leak", body=GOOD_BODY + "\nexport AWS_KEY=AKIAABCDEFGHIJKLMNOP\n")
    concept(repo, "cred", body=GOOD_BODY + "\npassword: hunter22hunter\n")
    concept(repo, "fine", body=GOOD_BODY + "\nset token: <your-token> or $TOKEN\n")
    errs = msgs(repo, "error")
    assert any(e.startswith("leak: looks like a secret (aws-access-key)") for e in errs)
    assert any(e.startswith("cred: looks like a secret (credential-assignment)") for e in errs)
    assert not any(e.startswith("fine:") for e in errs)


def test_timestamp_shapes(repo):
    concept(repo, "ts", meta=GOOD_META + "generated: {by: okf-wiki/haiku, at: 2026-06-30}\n"
            "stale_after: 2026-12-31\n")
    errs = msgs(repo, "error")
    assert any("generated.at '2026-06-30'" in e for e in errs)
    assert any("stale_after '2026-12-31'" in e for e in errs)


def test_bare_verified_mapping_is_accepted(repo):
    concept(repo, "v", meta=GOOD_META + "verified: {by: human:dave, at: 2026-07-01T09:00:00+02:00}\n")
    assert msgs(repo, "error") == []


def test_warnings(repo):
    long_desc = "x" * 201
    concept(repo, "w", meta=f"type: gotcha\ntitle: W\ndescription: {long_desc}\n",
            body="\nSee [missing](./nope.md) and [abs](/x.md) and [^s9].\n")
    warns = msgs(repo, "warn")
    assert "w: description is 201 chars; keep it one claim of at most 200" in warns
    assert "w: no `## Verify` section" in warns
    assert "w: broken link ./nope.md" in warns
    assert "w: link /x.md is bundle-absolute; use a relative ./ link" in warns
    assert "w: footnote [^s9] has no matching sources[].id" in warns


def test_verify_needs_an_anchor_or_none(repo):
    concept(repo, "n", body="\n## Verify\n\n- none: vendor behaviour, not in this repo\n")
    concept(repo, "e", body="\n## Verify\n\nrun the thing\n")
    warns = msgs(repo, "warn")
    assert not any(w.startswith("n: ") and "Verify" in w for w in warns)
    assert "e: unparsed Verify line: run the thing" in warns
    assert "e: `## Verify` has no anchor and no `- none: <reason>` line" in warns


def test_hidden_dirs_and_reserved_files_are_not_concepts(repo):
    concept(repo, "a")
    (repo / ".wiki" / ".cache").mkdir()
    (repo / ".wiki" / ".cache" / "x.md").write_text("junk")
    (repo / ".wiki" / "log.md").write_text("# Log\n")
    assert [c.id for c in okf.load(repo / ".wiki")] == ["a"]


def test_index_frontmatter_may_only_carry_okf_version(repo):
    concept(repo, "a")
    (repo / ".wiki" / "index.md").write_text('---\nokf_version: "0.2"\ntitle: x\n---\n')
    assert "index: root index.md frontmatter may only carry okf_version" in msgs(repo, "error")


def test_validate_refuses_without_a_bundle(tmp_path):
    r = run(tmp_path, "validate")
    assert r.returncode == 2
    assert r.stdout.splitlines()[-1].startswith("okf: validate refused no .wiki/")


def test_regex_classes_in_code_are_not_footnotes(repo):
    concept(repo, "rx", body=GOOD_BODY + "\nMatch `[^\\s]` and `[^:@\\s/]` and `[^/]`.\n")
    assert not any("footnote" in w for w in msgs(repo, "warn"))


def test_bom_and_crlf_files_load_cleanly(repo):
    raw = ("﻿---\r\n" + GOOD_META.replace("\n", "\r\n") + "---\r\n" + GOOD_BODY.replace("\n", "\r\n"))
    (repo / ".wiki" / "win.md").write_bytes(raw.encode("utf-8"))
    assert msgs(repo, "error") == []


def test_non_utf8_file_is_an_error_not_a_crash(repo):
    (repo / ".wiki" / "latin.md").write_bytes(b"---\ntype: gotcha\ntitle: caf\xe9\n---\n")
    assert any(e.startswith("latin: frontmatter:") for e in msgs(repo, "error"))


def test_identifiers_and_env_lookups_are_not_secrets(repo):
    body = GOOD_BODY + ('\n`token = os.getenv("GH_TOKEN")` and `secret: app-db-credentials` and '
                        '`api_key=settings.OPENAI_KEY` and `password: ${DB_PASSWORD}`\n')
    concept(repo, "code", body=body)
    assert not any("secret" in e for e in msgs(repo, "error"))
