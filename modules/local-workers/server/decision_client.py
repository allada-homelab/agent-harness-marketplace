"""Client for the decision model's /v1/systemone: validate a batch, send it concurrently, flag weak answers.

Speaks both servers `decision-default` has had: H2O-Lightning's shim and vllm-srun (d3-ultra). The wire
shape sent is the one both accept: images travel in the top-level `images` list, never as `data:` URIs
inside `state` (vllm-srun would read those as text), and `threshold` is applied here, not by the server
(vllm-srun rejects the field).

Stdlib only, so tests import it without the MCP SDK.
"""

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

MAX_DECISIONS = 128
MAX_OPTIONS = 255  # the shim's label set
MAX_IMAGES = 4  # per request, the shim's limit
LOW_CONFIDENCE = 0.5
DEFAULT_FLOOR = 0.801  # serve_config.json noul_floor, used when /health is unreachable
DEFAULT_MAX_STATE_TOKENS = 32000
TYPES = ("choice", "noul", "score")


def _count_images(value: Any) -> int:
    if isinstance(value, str):
        return 1 if value.startswith("data:image/") else 0
    if isinstance(value, dict):
        return sum(_count_images(v) for v in value.values())
    if isinstance(value, list):
        return sum(_count_images(v) for v in value)
    return 0


def _question_error(qid: str, q: Any) -> str | None:
    if not isinstance(q, dict):
        return f"question {qid}: must be an object"
    typ = q.get("type")
    # Required here because the shim silently treats a missing type as `choice`.
    if typ not in TYPES:
        return f"question {qid}: type must be one of {list(TYPES)}, got {typ!r}"
    instructions = q.get("instructions", "")
    if not isinstance(instructions, (str, dict, list)):
        return f"question {qid}: instructions must be a string, object or array"
    criteria = q.get("criteria")
    if typ == "choice":
        if not isinstance(criteria, dict) or not criteria:
            return f"question {qid}: choice criteria must be a non-empty object mapping option -> description"
        if len(criteria) > MAX_OPTIONS:
            return f"question {qid}: choice supports at most {MAX_OPTIONS} options, got {len(criteria)}"
    elif typ == "score":
        if not isinstance(criteria, list) or not criteria:
            return f"question {qid}: score criteria must be a non-empty ordered array of level descriptions"
    else:
        if criteria is not None and not isinstance(criteria, dict):
            return f"question {qid}: noul criteria must be an object with true/false descriptions"
        threshold = q.get("threshold")
        if threshold is not None and (
            isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1
        ):
            return f"question {qid}: threshold must be a number in [0, 1]"
    return None


def validate_item(item: Any) -> str | None:
    """The reason this item can't be sent, or None."""
    if not isinstance(item, dict):
        return "item must be an object"
    if "state" not in item:
        return "item needs a `state` (the record: text or JSON)"
    questions = item.get("questions")
    if not isinstance(questions, dict) or not questions:
        return "item needs a non-empty `questions` object"
    images = item.get("images")
    if images is not None and not isinstance(images, list):
        return "images must be a list"
    n_images = len(images or []) + _count_images(item["state"])
    if n_images > MAX_IMAGES:
        return f"{n_images} images; the decision model reads at most {MAX_IMAGES} per item"
    for qid, q in questions.items():
        if err := _question_error(qid, q):
            return err
    return None


def validate_items(items: Any) -> tuple[list[dict], str | None]:
    """Batch-level checks; returns the items with `id` filled in, or a whole-call error."""
    if not isinstance(items, list) or not items:
        return [], "items must be a list with at least one item"
    normalized, seen, decisions = [], set(), 0
    for index, it in enumerate(items):
        it = dict(it) if isinstance(it, dict) else {"_invalid": it}
        item_id = it.get("id", str(index))
        if not isinstance(item_id, str):
            return [], f"item {index}: id must be a string"
        if item_id in seen:
            return [], f"duplicate item id {item_id!r}"
        seen.add(item_id)
        it["id"] = item_id
        if isinstance(it.get("questions"), dict):
            decisions += len(it["questions"])
        normalized.append(it)
    if decisions > MAX_DECISIONS:
        return [], f"{decisions} decisions in one call; the limit is {MAX_DECISIONS} — split the batch"
    return normalized, None


def fetch_health(base_url: str, timeout: float = 5) -> dict:
    """The server's yes/no floor and state-token cap; the shipped shim values, marked `fallback`, when unreadable.

    vllm-srun (d3) answers /health without `noul_floor` and rejects an over-long state with a 400
    instead of truncating it, so there is no cap to compare usage against. It has no floor either:
    a coin flip comes back as itself (0.486 measured), so the shim's band is applied here instead.
    """
    try:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=timeout) as r:
                body = json.load(r)
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())  # a cold server answers 503 but its body still says what it is
        if "noul_floor" not in body and "status" in body:
            return {"noul_floor": DEFAULT_FLOOR, "max_state_tokens": None}
        return {
            "noul_floor": float(body["noul_floor"]["value"]),
            "max_state_tokens": int(body["max_state_tokens"]),
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {"noul_floor": DEFAULT_FLOOR, "max_state_tokens": DEFAULT_MAX_STATE_TOKENS, "fallback": True}


def _post(base_url: str, body: dict, timeout: float) -> tuple[int | None, dict | str]:
    """(HTTP status, parsed body) — status None means the request never got an HTTP answer."""
    req = urllib.request.Request(
        f"{base_url}/v1/systemone", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:500]
    except (OSError, ValueError) as e:
        return None, f"{type(e).__name__}: {e}"


def _annotate(answers: dict, floor: float) -> None:
    for answer in answers.values():
        if answer.get("type") == "noul" and floor:  # floor 0 = the shim's floor is turned off
            value = answer.get("noul")
            # Inside the band the model was near a coin flip. The shim reports those as exactly
            # floor / 1-floor; vllm-srun reports the value itself.
            answer["floored"] = isinstance(value, float) and max(value, 1 - value) < floor + 1e-9
            if not answer["floored"]:
                del answer["floored"]
        elif isinstance(answer.get("confidence"), (int, float)) and answer["confidence"] < LOW_CONFIDENCE:
            answer["low_confidence"] = True


def _detail(body: dict | str) -> str:
    if not isinstance(body, dict):
        return body
    error = body.get("error")  # vllm-srun: {"error": {"code", "message"}}
    if isinstance(error, dict) and "message" in error:
        return str(error["message"])
    return str(body.get("detail", body))


def _lift_images(value: Any, images: list[str]) -> Any:
    """`value` with every `data:image/` string moved to `images` and named `[image k]` where it stood."""
    if isinstance(value, str) and value.startswith("data:image/"):
        images.append(value)
        return f"[image {len(images)}]"
    if isinstance(value, dict):
        return {k: _lift_images(v, images) for k, v in value.items()}
    if isinstance(value, list):
        return [_lift_images(v, images) for v in value]
    return value


def _apply_thresholds(questions: dict, answers: dict) -> None:
    """What the H2O shim did server-side: `decision` = noul >= threshold, on the (possibly floored) value."""
    for qid, q in questions.items():
        threshold = q.get("threshold")
        answer = answers.get(qid, {})
        if threshold is not None and isinstance(answer.get("noul"), (int, float)):
            answer["threshold"] = threshold
            answer["decision"] = answer["noul"] >= threshold


def _run_one(base_url: str, it: dict, health: dict, timeout: float) -> dict:
    result: dict = {"id": it["id"]}
    if err := validate_item(it):
        return {**result, "status": "invalid", "error": err}
    images = list(it.get("images") or [])
    body: dict[str, Any] = {
        "state": _lift_images(it["state"], images),
        "questions": {qid: {k: v for k, v in q.items() if k != "threshold"} for qid, q in it["questions"].items()},
    }
    if images:
        body["images"] = images
    status, resp = _post(base_url, body, timeout)
    if status is None:
        return {**result, "status": "error", "error": f"unreachable: {resp}", "_connection": True}
    if status in (400, 422):
        return {**result, "status": "invalid", "error": _detail(resp)}
    if status != 200 or not isinstance(resp, dict):
        return {**result, "status": "error", "error": f"HTTP {status}: {_detail(resp)}"}
    answers = resp.get("answers")
    if not isinstance(answers, dict) or set(it["questions"]) - set(answers):
        missing = sorted(set(it["questions"]) - set(answers if isinstance(answers, dict) else {}))
        return {**result, "status": "error", "error": f"HTTP 200 but no answer for {missing}: {_detail(resp)[:300]}"}
    _annotate(answers, health["noul_floor"])
    _apply_thresholds(it["questions"], answers)
    usage = resp.get("usage", {})
    cap = health["max_state_tokens"]
    truncated = cap is not None and int(usage.get("input_tokens") or 0) >= cap
    return {**result, "status": "ok", "answers": answers, "usage": usage, "possibly_truncated": truncated}


def decide_batch(
    base_url: str, items: Any, concurrency: int = 8, timeout: float = 30, health: dict | None = None
) -> dict:
    """Send every valid item to the shim (up to `concurrency` at once) and return per-item results."""
    base_url = base_url.rstrip("/")
    normalized, err = validate_items(items)
    if err:
        return {"error": err}
    health = health or fetch_health(base_url)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(lambda it: _run_one(base_url, it, health, timeout), normalized))
    sent = [r for r in results if r["status"] != "invalid"]
    if sent and all(r.get("_connection") for r in sent):
        return {"error": f"decision model unreachable at {base_url}: {sent[0]['error']}"}
    for r in results:
        r.pop("_connection", None)
    answers = [a for r in results for a in r.get("answers", {}).values()]
    summary = {
        "items": len(results),
        "ok": sum(r["status"] == "ok" for r in results),
        "invalid": sum(r["status"] == "invalid" for r in results),
        "error": sum(r["status"] == "error" for r in results),
        "floored": sum(bool(a.get("floored")) for a in answers),
        "low_confidence": sum(bool(a.get("low_confidence")) for a in answers),
        "possibly_truncated": sum(bool(r.get("possibly_truncated")) for r in results),
    }
    return {"results": results, "summary": summary}
