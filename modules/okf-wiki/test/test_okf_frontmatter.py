from pathlib import Path

import pytest
from okf_testlib import okf

ACME = Path(__file__).resolve().parents[3] / "docs/planning/wiki/okf-upstream/sample-bundle-acme_retail"

ACCEPT = [
    ("type: gotcha\n", {"type": "gotcha"}),
    ("tags: [a, b]\n", {"tags": ["a", "b"]}),
    ("tags:\n  - a\n  - b\n", {"tags": ["a", "b"]}),
    ("tags:\n- a\n- b\n", {"tags": ["a", "b"]}),
    ("generated: { by: x/y, at: 2026-06-30T14:00:00Z }\n",
     {"generated": {"by": "x/y", "at": "2026-06-30T14:00:00Z"}}),
    ("verified:\n  - { by: human:jsmith@acme, at: 2026-07-01T09:00:00Z }\n",
     {"verified": [{"by": "human:jsmith@acme", "at": "2026-07-01T09:00:00Z"}]}),
    ("sources:\n  - id: s1\n    resource: policies/x.md\n    title: X & Y (FY2026)\n",
     {"sources": [{"id": "s1", "resource": "policies/x.md", "title": "X & Y (FY2026)"}]}),
    ("executor:\n  resource: skills/run.md\n  receipt: [job_id, result]\n",
     {"executor": {"resource": "skills/run.md", "receipt": ["job_id", "result"]}}),
    ('okf_version: "0.2"\n', {"okf_version": "0.2"}),
    ("usage_count: 12\n", {"usage_count": "12"}),
    ("title: it's fine # a comment\n", {"title": "it's fine"}),
    ("resource: https://x.example/a#frag\n", {"resource": "https://x.example/a#frag"}),
    ("not:\n  - term: \"a, b\"\n    why: 'it''s old'\n", {"not": [{"term": "a, b", "why": "it's old"}]}),
    ("empty:\n", {"empty": ""}),
    ("list: []\nmap: {}\n", {"list": [], "map": {}}),
]


@pytest.mark.parametrize("text,expected", ACCEPT)
def test_accepts_the_subset(text, expected):
    assert okf.parse_frontmatter(text) == expected


REJECT = [
    ("body: |\n  multi\n", "outside the okf-wiki YAML subset"),
    ("a: &anchor x\n", "outside the okf-wiki YAML subset"),
    ("a: !!str x\n", "outside the okf-wiki YAML subset"),
    ("a: 1\na: 2\n", "duplicate key"),
    ("\ta: 1\n", "tab indentation"),
    ("a: [1, 2\n", "expected ',' or ']'"),
    ('a: "open\n', "unterminated"),
    ("- a\n- b\n", "must be a mapping"),
    ("a: 1\n    b: 2\n", "unexpected indentation"),
    ("just text\n", "expected `key: value`"),
]


@pytest.mark.parametrize("text,msg", REJECT)
def test_rejects_outside_the_subset(text, msg):
    with pytest.raises(okf.FrontmatterError, match=msg.replace("(", r"\(").replace("[", r"\[")):
        okf.parse_frontmatter(text)


@pytest.mark.parametrize("text,expected", ACCEPT)
def test_dump_round_trips(text, expected):
    assert okf.parse_frontmatter(okf.dump_frontmatter(expected)) == expected


def test_dump_orders_known_keys_then_unknown_in_original_order():
    meta = {"zeta": "1", "sources": [], "type": "gotcha", "alpha": "2", "title": "T"}
    assert okf.dump_frontmatter(meta).splitlines() == [
        "type: gotcha", "title: T", "sources: []", "zeta: 1", "alpha: 2"]


def test_dump_quotes_what_yaml_would_retype_or_misparse():
    out = okf.dump_frontmatter({"a": "yes", "b": "x: y", "c": "", "d": "-x", "e": "<fill: t>"})
    assert out == 'a: "yes"\nb: "x: y"\nc: ""\nd: "-x"\ne: "<fill: t>"\n'


def test_timestamps_stay_strings():
    meta = okf.parse_frontmatter("stale_after: 2026-12-31T00:00:00Z\n")
    assert meta["stale_after"] == "2026-12-31T00:00:00Z"


def test_every_acme_retail_concept_parses_and_round_trips():
    files = [p for p in ACME.rglob("*.md") if p.name not in ("index.md", "log.md")]
    assert len(files) >= 8
    for p in files:
        fm, _ = okf.split(okf.read_text(p))
        meta = okf.parse_frontmatter(fm)
        assert meta["type"], p
        assert okf.parse_frontmatter(okf.dump_frontmatter(meta)) == meta, p


def test_split_requires_terminated_frontmatter():
    with pytest.raises(okf.FrontmatterError, match="unterminated"):
        okf.split("---\ntype: x\n")
    with pytest.raises(okf.FrontmatterError, match="must start with ---"):
        okf.split("# no frontmatter\n")
