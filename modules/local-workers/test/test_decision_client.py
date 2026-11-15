import socket

import pytest
from fake_shim import FLOOR, FakeShim

from decision_client import decide_batch, fetch_health, validate_item, validate_items

NOUL = {"type": "noul", "instructions": "Is it a bug?", "criteria": {"true": "bug", "false": "not a bug"}}
CHOICE = {"type": "choice", "instructions": "Priority?", "criteria": {"p1": "down", "p2": "degraded"}}
SCORE = {"type": "score", "instructions": "Urgency?", "criteria": ["low", "medium", "high"]}


def item(state: object = "a ticket", **questions):
    return {"state": state, "questions": questions or {"q": NOUL}}


@pytest.fixture
def shim():
    with FakeShim() as s:
        yield s


def dead_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("question", "needle"),
    [
        ({"instructions": "x", "criteria": {"a": "b"}}, "type"),
        ({"type": "yesno", "criteria": {}}, "type"),
        ({"type": "choice", "criteria": ["a", "b"]}, "object"),
        ({"type": "choice", "criteria": {}}, "object"),
        ({"type": "choice", "criteria": {f"o{i}": "d" for i in range(256)}}, "255"),
        ({"type": "score", "criteria": {"low": "x"}}, "ordered array"),
        ({"type": "score", "criteria": []}, "ordered array"),
        ({"type": "noul", "criteria": ["yes", "no"]}, "true/false"),
        ({"type": "noul", "threshold": 1.5}, "threshold"),
        ({"type": "noul", "threshold": "high"}, "threshold"),
        ({"type": "noul", "instructions": 5}, "instructions"),
    ],
)
def test_invalid_questions_are_named(question, needle):
    err = validate_item({"state": "s", "questions": {"q1": question}})
    assert err is not None and needle in err and "q1" in err


@pytest.mark.parametrize("question", [NOUL, CHOICE, SCORE, {"type": "noul"}, {"type": "noul", "threshold": 0.9},
                                      {"type": "choice", "criteria": {"a": None, "b": "desc"}},
                                      {"type": "score", "instructions": ["step 1", "step 2"], "criteria": ["a"]}])
def test_valid_questions_pass(question):
    assert validate_item({"state": {"any": "json"}, "questions": {"q": question}}) is None


def test_item_needs_state_and_questions():
    assert "state" in validate_item({"questions": {"q": NOUL}})
    assert "questions" in validate_item({"state": "s"})
    assert "questions" in validate_item({"state": "s", "questions": {}})


def test_images_counted_across_list_and_nested_state():
    uri = "data:image/png;base64,AAAA"
    ok = {"state": {"receipt": uri, "pages": [uri]}, "images": [uri, uri], "questions": {"q": NOUL}}
    assert validate_item(ok) is None
    over = {"state": {"receipt": uri, "pages": [{"p": uri}]}, "images": [uri, uri, uri], "questions": {"q": NOUL}}
    assert "5 images" in validate_item(over)


def test_batch_level_rules():
    _, err = validate_items([])
    assert "at least one" in err
    _, err = validate_items([{**item(), "id": "a"}, {**item(), "id": "a"}])
    assert "duplicate" in err and "a" in err
    big = [item(**{f"q{i}": NOUL for i in range(64)}) for _ in range(2)]
    norm, err = validate_items(big)
    assert err is None and [i["id"] for i in norm] == ["0", "1"]
    _, err = validate_items([*big, item()])
    assert "129" in err and "128" in err


def test_ids_default_to_index_and_must_be_strings():
    norm, err = validate_items([item(), {**item(), "id": "x"}])
    assert err is None and [i["id"] for i in norm] == ["0", "x"]
    _, err = validate_items([{**item(), "id": 3}])
    assert "id" in err


# ---------------------------------------------------------------- health


def test_health_reads_floor(shim):
    assert fetch_health(shim.url) == {"noul_floor": FLOOR, "max_state_tokens": 32000}


def test_health_falls_back_when_unreachable():
    assert fetch_health(dead_url(), timeout=1) == {"noul_floor": 0.801, "max_state_tokens": 32000, "fallback": True}


def test_health_reads_floor_from_a_cold_503():
    with FakeShim(health_status=503) as cold:
        assert fetch_health(cold.url) == {"noul_floor": FLOOR, "max_state_tokens": 32000}


# ---------------------------------------------------------------- batches


def test_pass_through_and_summary(shim):
    out = decide_batch(shim.url, [item("t", a=NOUL, b=CHOICE, c=SCORE)])
    r = out["results"][0]
    assert r["status"] == "ok" and r["id"] == "0"
    assert r["answers"]["a"]["noul"] == 0.95 and "floored" not in r["answers"]["a"]
    assert r["answers"]["b"]["choice"] == "p1" and "low_confidence" not in r["answers"]["b"]
    assert r["answers"]["c"]["legend"] == {"0": "low", "1": "medium", "2": "high"}
    assert r["possibly_truncated"] is False
    assert out["summary"] == {"items": 1, "ok": 1, "invalid": 0, "error": 0, "floored": 0,
                              "low_confidence": 0, "possibly_truncated": 0}
    assert shim.requests[0] == {"state": "t", "questions": {"a": NOUL, "b": CHOICE, "c": SCORE}}


def test_floored_on_both_sides(shim):
    out = decide_batch(shim.url, [item("coinflip"), item("coinflip-no")])
    assert [r["answers"]["q"]["floored"] for r in out["results"]] == [True, True]
    assert out["summary"]["floored"] == 2


def test_floor_turned_off_flags_nothing(shim):
    out = decide_batch(shim.url, [item("coinflip")], health={"noul_floor": 0.0, "max_state_tokens": 32000})
    assert "floored" not in out["results"][0]["answers"]["q"]


@pytest.mark.parametrize("state", ["noanswers", "partial"])
def test_200_without_every_answer_is_an_error(shim, state):
    out = decide_batch(shim.url, [item(state, a=NOUL, b=CHOICE)])
    assert out["results"][0]["status"] == "error" and "answer" in out["results"][0]["error"]


def test_low_confidence_on_choice_and_score(shim):
    out = decide_batch(shim.url, [item("unsure", b=CHOICE, c=SCORE)])
    answers = out["results"][0]["answers"]
    assert answers["b"]["low_confidence"] is True and answers["c"]["low_confidence"] is True
    assert out["summary"]["low_confidence"] == 2


def test_possibly_truncated(shim):
    out = decide_batch(shim.url, [item("huge")])
    assert out["results"][0]["possibly_truncated"] is True and out["summary"]["possibly_truncated"] == 1


def test_mixed_batch_maps_each_failure(shim):
    items = [item("fine"), item("reject"), item("upstream"), {"state": "x", "questions": {"q": {"type": "bad"}}}]
    out = decide_batch(shim.url, items)
    assert [r["status"] for r in out["results"]] == ["ok", "invalid", "error", "invalid"]
    assert "malformed question" in out["results"][1]["error"]
    assert "502" in out["results"][2]["error"]
    assert "type" in out["results"][3]["error"]
    assert len(shim.requests) == 3  # the locally invalid item is never sent
    assert out["summary"]["ok"] == 1 and out["summary"]["invalid"] == 2 and out["summary"]["error"] == 1


def test_batch_level_error_sends_nothing(shim):
    out = decide_batch(shim.url, [{**item(), "id": "a"}, {**item(), "id": "a"}])
    assert "duplicate" in out["error"] and shim.requests == []


def test_all_unreachable_is_one_top_level_error():
    url = dead_url()
    out = decide_batch(url, [item(), item()], timeout=1)
    assert url in out["error"] and "results" not in out


def test_concurrency_cap(shim):
    decide_batch(shim.url, [item("slow") for _ in range(12)], concurrency=3)
    assert shim.max_in_flight <= 3 and len(shim.requests) == 12


def test_images_are_forwarded_and_id_is_not_sent(shim):
    uri = "data:image/png;base64,AAAA"
    decide_batch(shim.url, [{"id": "r", "state": "s", "images": [uri], "questions": {"q": NOUL}}])
    assert shim.requests[0] == {"state": "s", "images": [uri], "questions": {"q": NOUL}}


# ---------------------------------------------------------------- vllm-srun (d3-ultra) compatibility

URI = "data:image/png;base64,AAAA"


@pytest.fixture
def srun():
    with FakeShim(srun=True) as s:
        yield s


def test_health_of_srun_applies_the_band_and_has_no_cap(srun):
    assert fetch_health(srun.url) == {"noul_floor": 0.801, "max_state_tokens": None}


def test_health_of_a_loading_srun_is_not_a_fallback():
    with FakeShim(health_status=503, srun=True) as cold:
        assert fetch_health(cold.url) == {"noul_floor": 0.801, "max_state_tokens": None}


def test_state_images_move_to_the_images_list(srun):
    decide_batch(srun.url, [{"state": {"receipt": URI, "pages": [URI]}, "images": [URI], "questions": {"q": NOUL}}])
    assert srun.requests[0]["state"] == {"receipt": "[image 2]", "pages": ["[image 3]"]}
    assert srun.requests[0]["images"] == [URI, URI, URI]


def test_threshold_is_not_sent(srun):
    decide_batch(srun.url, [item(q={**NOUL, "threshold": 0.9})])
    assert srun.requests[0]["questions"] == {"q": NOUL}


def test_threshold_decision_is_computed_from_noul(srun):
    out = decide_batch(srun.url, [item(yes={**NOUL, "threshold": 0.9}, no={**NOUL, "threshold": 0.99})])
    answers = out["results"][0]["answers"]
    assert (answers["yes"]["threshold"], answers["yes"]["decision"]) == (0.9, True)
    assert (answers["no"]["threshold"], answers["no"]["decision"]) == (0.99, False)


def test_threshold_decision_keeps_the_shims_floor_semantics(shim):
    out = decide_batch(shim.url, [item("coinflip-no", q={**NOUL, "threshold": 0.5})])
    assert out["results"][0]["answers"]["q"] == {"type": "noul", "noul": 1.0 - FLOOR, "floored": True,
                                                 "threshold": 0.5, "decision": False}


def test_srun_error_message_is_reported(srun):
    out = decide_batch(srun.url, [item("reject")])
    assert out["results"][0] == {"id": "0", "status": "invalid", "error": "malformed question"}


def test_srun_never_marks_truncation(srun):
    """It rejects an over-long state with a 400 instead of cutting it."""
    out = decide_batch(srun.url, [item("huge")])
    assert out["results"][0]["possibly_truncated"] is False


def test_srun_coin_flip_is_floored_without_a_server_floor(srun):
    out = decide_batch(srun.url, [item("unsure"), item("t")])
    assert out["results"][0]["answers"]["q"]["floored"] is True
    assert "floored" not in out["results"][1]["answers"]["q"]  # 0.95 is a decision
