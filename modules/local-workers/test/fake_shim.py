"""A stand-in for the H2O-Lightning shim: behaviour is picked by a keyword in `state`."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FLOOR = 0.801


def _answer(q: dict, state: str) -> dict:
    typ = q["type"]
    if typ == "noul":
        if "coinflip-no" in state:
            return {"type": "noul", "noul": 1.0 - FLOOR}
        if "coinflip" in state:
            return {"type": "noul", "noul": FLOOR}
        if "unsure" in state:  # vllm-srun has no floor: d3-ultra-INT4 on an unsupported statement
            return {"type": "noul", "noul": 0.486}
        return {"type": "noul", "noul": 0.95}
    if typ == "score":
        n = len(q["criteria"])
        conf = 0.2 if "unsure" in state else 0.9
        return {"type": "score", "score": n - 1.0, "legend": {str(i): c for i, c in enumerate(q["criteria"])},
                "probabilities": {str(i): 1.0 / n for i in range(n)}, "confidence": conf}
    names = list(q["criteria"])
    conf = 0.2 if "unsure" in state else 0.9
    return {"type": "choice", "choice": names[0], "probabilities": {n: 1.0 / len(names) for n in names},
            "confidence": conf}


class FakeShim:
    """The H2O shim by default; with ``srun=True``, vllm-srun as measured 2026-11-05 on d3-ultra-INT4:
    /health has no floor, a `threshold` field is a 422, a data URI inside `state` is a 413 (it is read
    as text), and errors are ``{"error": {"code", "message"}}``."""

    def __init__(self, health_status: int = 200, srun: bool = False) -> None:
        self.health_status = health_status
        self.srun = srun
        self.in_flight = 0
        self.max_in_flight = 0
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        shim = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # quiet
                pass

            def _send(self, code: int, obj: dict) -> None:
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/health" and shim.srun:
                    status = "ready" if shim.health_status == 200 else "loading"
                    return self._send(shim.health_status, {"api_version": "3.2.0", "status": status, "model": "d3"})
                if self.path == "/health":
                    return self._send(shim.health_status, {"ok": shim.health_status == 200, "max_state_tokens": 32000,
                                                           "noul_floor": {"value": FLOOR, "source": "test"}})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with shim.lock:
                    shim.requests.append(body)
                    shim.in_flight += 1
                    shim.max_in_flight = max(shim.max_in_flight, shim.in_flight)
                try:
                    state = json.dumps(body["state"]) if not isinstance(body["state"], str) else body["state"]
                    if "slow" in state:
                        time.sleep(0.2)
                    if shim.srun and any("threshold" in q for q in body["questions"].values()):
                        return self._send(422, {"error": {"code": "question_failed", "message": "takes no threshold"}})
                    if shim.srun and "data:image/" in state:
                        return self._send(413, {"error": {"code": "request_too_large", "message": "out of memory"}})
                    if "reject" in state and shim.srun:
                        return self._send(422, {"error": {"code": "question_failed", "message": "malformed question"}})
                    if "reject" in state:
                        return self._send(422, {"detail": "malformed question"})
                    if "upstream" in state:
                        return self._send(502, {"detail": "vLLM failed"})
                    if "noanswers" in state:
                        return self._send(200, {"error": "proxy said no"})
                    tokens = 32074 if "huge" in state else 200
                    answers = {qid: _answer(q, state) for qid, q in body["questions"].items()}
                    if "partial" in state:
                        answers.pop(next(iter(answers)))
                    self._send(200, {"model": "fake", "answers": answers, "probability_source": "native",
                                     "usage": {"input_tokens": tokens, "output_tokens": 0, "latency_ms": 1.0}})
                finally:
                    with shim.lock:
                        shim.in_flight -= 1

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeShim":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
